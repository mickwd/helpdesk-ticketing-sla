"""Base de conocimiento: artículos vinculados a tickets resueltos y sugerencias."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import DONE_STATUSES, Category, Specialty
from app.models import KnowledgeArticle, KnowledgeArticleTicket, Ticket, User
from app.services.classification import normalize_text
from app.services.errors import ConflictError, NotFoundError, ValidationError

# fmt: off
STOPWORDS = frozenset(
    {
        "que", "con", "por", "para", "los", "las", "del", "una", "uno", "unos", "unas", "como",
        "pero", "mas", "sin", "sobre", "entre", "cuando", "desde", "hasta", "este", "esta",
        "esto", "estos", "estas", "ese", "esa", "eso", "hay", "muy", "ya", "tambien", "porque",
        "donde", "tengo", "tiene", "tienen", "puedo", "puede", "pueden", "hace", "hacer",
        "estan", "fue", "ser", "son", "mis", "sus", "nos", "les", "todo", "todos", "toda",
        "todas", "otro", "otra", "ahora", "hoy", "ayer", "favor", "buenas", "buenos", "dias",
        "tardes", "hola", "gracias", "necesito", "problema", "error", "usuario", "sistema",
        "funciona", "anda",
    }
)
# fmt: on
TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def tokenize(text: str) -> set[str]:
    return {t for t in TOKEN_RE.findall(normalize_text(text)) if t not in STOPWORDS}


@dataclass(frozen=True)
class Suggestion:
    article: KnowledgeArticle
    score: float
    matched: list[str]


def score_article(article: KnowledgeArticle, tokens: set[str]) -> tuple[float, list[str]]:
    keywords: set[str] = set()
    for keyword in article.keyword_list:
        keywords |= tokenize(keyword)
    title_tokens = tokenize(article.title)
    matched_kw = tokens & keywords
    matched_title = (tokens & title_tokens) - matched_kw
    score = 2.0 * len(matched_kw) + 1.0 * len(matched_title)
    return score, sorted(matched_kw | matched_title)


def suggest_articles(session: Session, text: str, limit: int = 3) -> list[Suggestion]:
    tokens = tokenize(text)
    if not tokens:
        return []
    suggestions = []
    for article in session.scalars(select(KnowledgeArticle)).all():
        score, matched = score_article(article, tokens)
        if score > 0:
            suggestions.append(Suggestion(article, score, matched))
    suggestions.sort(key=lambda s: (-s.score, s.article.id))
    return suggestions[:limit]


def _resolved_ticket(session: Session, ticket_id: int) -> Ticket:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise NotFoundError(f"El ticket {ticket_id} no existe")
    if ticket.status not in DONE_STATUSES:
        raise ConflictError("Solo se pueden vincular tickets resueltos o cerrados")
    return ticket


def create_article(
    session: Session,
    author: User,
    *,
    title: str,
    body: str,
    keywords: list[str],
    category: Category,
    specialty: Specialty | None,
    ticket_ids: list[int],
    now: datetime,
) -> KnowledgeArticle:
    if len(title.strip()) < 5 or len(body.strip()) < 20:
        raise ValidationError("El artículo necesita título (5+) y contenido (20+ caracteres)")
    tickets = [_resolved_ticket(session, tid) for tid in dict.fromkeys(ticket_ids)]
    article = KnowledgeArticle(
        title=title.strip(),
        body=body.strip(),
        keywords=", ".join(k.strip().lower() for k in keywords if k.strip()),
        category=Category(category),
        specialty=Specialty(specialty) if specialty else None,
        author_id=author.id,
        created_at=now,
        updated_at=now,
    )
    article.tickets = [KnowledgeArticleTicket(ticket_id=t.id) for t in tickets]
    session.add(article)
    session.flush()
    return article


def link_ticket(session: Session, article_id: int, ticket_id: int) -> KnowledgeArticle:
    article = session.get(KnowledgeArticle, article_id)
    if article is None:
        raise NotFoundError(f"El artículo {article_id} no existe")
    _resolved_ticket(session, ticket_id)
    if ticket_id not in article.ticket_ids:
        article.tickets.append(KnowledgeArticleTicket(ticket_id=ticket_id))
        session.flush()
    return article
