"""Clasificación automática de tickets.

1. Reglas por palabras clave / regex definidas en YAML (siempre disponibles).
2. Modelo opcional TF-IDF + LogisticRegression (solo si scikit-learn está instalado),
   usado como respaldo cuando ninguna regla coincide.
"""

from __future__ import annotations

import csv
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import Settings
from app.domain.enums import Category, Level, Specialty

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """Minúsculas y sin tildes, para que 'Contraseña' y 'contrasena' coincidan."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@dataclass(frozen=True)
class Rule:
    name: str
    patterns: tuple[re.Pattern[str], ...]
    category: Category
    specialty: Specialty
    level: Level
    description: str = ""


@dataclass(frozen=True)
class ClassificationResult:
    category: Category
    specialty: Specialty
    level: Level
    source: str  # "reglas", "modelo" o "default"
    rule: str | None = None
    score: float = 0.0
    matched: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[Rule, ...]
    default_category: Category
    default_specialty: Specialty
    default_level: Level


def parse_rules(raw: dict[str, Any]) -> RuleSet:
    default = raw.get("default", {})
    rules = tuple(
        Rule(
            name=item["name"],
            patterns=tuple(re.compile(p) for p in item["patterns"]),
            category=Category(item["category"]),
            specialty=Specialty(item["specialty"]),
            level=Level(item.get("level", "N1")),
            description=item.get("description", ""),
        )
        for item in raw.get("rules", [])
    )
    return RuleSet(
        rules=rules,
        default_category=Category(default.get("category", "otro")),
        default_specialty=Specialty(default.get("specialty", "aplicaciones")),
        default_level=Level(default.get("level", "N1")),
    )


@lru_cache(maxsize=8)
def load_rules(path: Path) -> RuleSet:
    with Path(path).open(encoding="utf-8") as fh:
        return parse_rules(yaml.safe_load(fh))


def classify_with_rules(
    rules: RuleSet, title: str, description: str
) -> ClassificationResult | None:
    norm_title = normalize_text(title)
    norm_body = normalize_text(description)
    best: tuple[float, int, Rule, list[str]] | None = None
    for index, rule in enumerate(rules.rules):
        score = 0.0
        matched: list[str] = []
        for pattern in rule.patterns:
            in_title = pattern.search(norm_title)
            in_body = pattern.search(norm_body)
            if in_title or in_body:
                score += 2 if in_title else 1
                matched.append((in_title or in_body).group(0))  # type: ignore[union-attr]
        if score == 0:
            continue
        # Mayor puntaje gana; ante empate, la regla definida primero
        if best is None or score > best[0]:
            best = (score, index, rule, matched)
    if best is None:
        return None
    score, _, rule, matched = best
    return ClassificationResult(
        category=rule.category,
        specialty=rule.specialty,
        level=rule.level,
        source="reglas",
        rule=rule.name,
        score=score,
        matched=matched,
    )


class MlClassifier:
    """TF-IDF + regresión logística entrenado con el CSV de ejemplo.

    Se entrena en memoria la primera vez que se usa. Si scikit-learn no está
    instalado, `available` queda en False y el sistema funciona solo con reglas.
    """

    def __init__(self, training_csv: Path, min_confidence: float = 0.35) -> None:
        self.training_csv = Path(training_csv)
        self.min_confidence = min_confidence
        self._pipeline: Any = None
        self._tried = False

    @property
    def available(self) -> bool:
        self._ensure_trained()
        return self._pipeline is not None

    def _ensure_trained(self) -> None:
        if self._tried:
            return
        self._tried = True
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import make_pipeline
        except ImportError:
            logger.info("scikit-learn no está instalado: se usa solo clasificación por reglas")
            return
        if not self.training_csv.exists():
            logger.warning("No existe el CSV de entrenamiento %s", self.training_csv)
            return
        texts: list[str] = []
        labels: list[str] = []
        with self.training_csv.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                texts.append(normalize_text(f"{row['title']} {row['description']}"))
                labels.append(f"{row['category']}|{row['specialty']}")
        if len(set(labels)) < 2:
            return
        pipeline = make_pipeline(
            TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True),
            LogisticRegression(max_iter=2000),
        )
        pipeline.fit(texts, labels)
        self._pipeline = pipeline

    def predict(self, title: str, description: str) -> tuple[Category, Specialty, float] | None:
        self._ensure_trained()
        if self._pipeline is None:
            return None
        text = normalize_text(f"{title} {description}")
        probabilities = self._pipeline.predict_proba([text])[0]
        best_index = int(probabilities.argmax())
        confidence = float(probabilities[best_index])
        if confidence < self.min_confidence:
            return None
        category, specialty = self._pipeline.classes_[best_index].split("|")
        return Category(category), Specialty(specialty), confidence


class TicketClassifier:
    def __init__(self, rules: RuleSet, ml: MlClassifier | None = None) -> None:
        self.rules = rules
        self.ml = ml

    def classify(self, title: str, description: str) -> ClassificationResult:
        by_rules = classify_with_rules(self.rules, title, description)
        if by_rules is not None:
            return by_rules
        if self.ml is not None:
            prediction = self.ml.predict(title, description)
            if prediction is not None:
                category, specialty, confidence = prediction
                return ClassificationResult(
                    category=category,
                    specialty=specialty,
                    level=self.rules.default_level,
                    source="modelo",
                    score=round(confidence, 3),
                )
        return ClassificationResult(
            category=self.rules.default_category,
            specialty=self.rules.default_specialty,
            level=self.rules.default_level,
            source="default",
        )


def build_classifier(settings: Settings) -> TicketClassifier:
    rules = load_rules(settings.classification_rules_path)
    ml = MlClassifier(settings.classifier_training_csv) if settings.ml_enabled else None
    return TicketClassifier(rules, ml)
