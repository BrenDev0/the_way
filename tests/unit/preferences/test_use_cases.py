from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.preferences import config
from src.preferences import use_cases as preferences_use_cases
from src.preferences.domain import Preference


class Store:
    def __init__(self, texts=()):
        self.user_id = uuid4()
        self.saved = [self._make(text) for text in texts]

    def _make(self, text):
        return Preference(
            id=uuid4(),
            organization_id=uuid4(),
            user_id=self.user_id,
            text=text,
            created_at=datetime.now(UTC),
        )

    async def list_for_user(self, user_id):
        return list(self.saved)

    async def create(self, preference):
        made = self._make(preference.text)
        self.saved.append(made)
        return made

    async def delete_for_user(self, preference_id, user_id):
        before = len(self.saved)
        self.saved = [p for p in self.saved if p.id != preference_id]
        return len(self.saved) < before


async def remember(store, text):
    return await preferences_use_cases.remember(
        uuid4(), store.user_id, text, store.list_for_user, store.create
    )


async def test_whitespace_is_collapsed():
    store = Store()

    saved = await remember(store, "  answer   in\nSpanish  ")

    assert saved.text == "answer in Spanish"


async def test_the_same_rule_is_not_saved_twice_whatever_the_case():
    store = Store(["Answer in Spanish"])

    with pytest.raises(ConflictError) as exc:
        await remember(store, "answer in spanish")

    assert exc.value.code == "preference_already_exists"


async def test_an_empty_preference_is_refused():
    with pytest.raises(ValidationError):
        await remember(Store(), "   ")


async def test_a_document_is_not_a_preference():
    with pytest.raises(ValidationError) as exc:
        await remember(Store(), "x" * (config.MAX_PREFERENCE_CHARS + 1))

    assert exc.value.code == "preference_too_long"


async def test_the_list_is_capped():
    store = Store([f"rule {n}" for n in range(config.MAX_PREFERENCES_PER_USER)])

    with pytest.raises(ConflictError) as exc:
        await remember(store, "one more")

    assert exc.value.code == "preference_limit_reached"


async def test_forgetting_a_missing_preference_is_not_found():
    with pytest.raises(NotFoundError):
        await preferences_use_cases.forget(uuid4(), uuid4(), Store().delete_for_user)


def test_the_block_tells_the_model_to_follow_them_silently():
    store = Store(["Answer in Spanish", "Deliver reports to Reports"])

    block = preferences_use_cases.render(store.saved)

    assert "without mentioning them" in block
    assert "- Answer in Spanish" in block


def test_no_preferences_means_no_block():
    assert preferences_use_cases.render([]) == ""
