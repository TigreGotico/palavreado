"""An entity re-registration replaces its value set, and needs a skill_id.

OVOS-INTENT-4 §8.1: "Registering an intent whose ``(session_id, skill_id,
intent_name, lang, method)`` quintuple matches an existing registration
**replaces** it (INTENT-3 §6.1) -- no prior deregister needed. ... The same
rule applies to entities, keyed on the quadruple ``(session_id, skill_id,
entity_name, lang)``."

Accumulating instead of replacing keeps values the producer has dropped, so a
skill that removes a value from its ``.entity`` file goes on matching it.
"""
import unittest
from unittest import mock

from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage

from palavreado.opm import PalavreadoPipeline


def _pipeline(langs=("en-US",)):
    with mock.patch("palavreado.opm.Configuration",
                    return_value={"lang": langs[0],
                                  "secondary_langs": list(langs[1:])}):
        return PalavreadoPipeline(bus=mock.Mock(), config={})


def _register(pipe, samples, skill_id="a.skill", name="genre", lang="en-US"):
    pipe.handle_register_entity(Message(
        str(SpecMessage.ENTITY_REGISTER),
        {"skill_id": skill_id, "entity_name": name,
         "samples": samples, "lang": lang}))


class SpecEntityReplacementTest(unittest.TestCase):
    def setUp(self):
        self.pipe = _pipeline()

    def _values(self, name="genre", lang="en-US"):
        return self.pipe._vocab[lang].get(name)

    def test_a_re_registration_replaces_the_value_set(self):
        _register(self.pipe, ["jazz", "rock"])
        self.assertEqual(self._values(), ["jazz", "rock"])
        _register(self.pipe, ["jazz"])
        self.assertEqual(self._values(), ["jazz"],
                         "a dropped value must not survive re-registration")

    def test_duplicates_within_one_payload_collapse(self):
        _register(self.pipe, ["jazz", "jazz", "rock"])
        self.assertEqual(self._values(), ["jazz", "rock"])

    def test_a_payload_without_skill_id_is_rejected(self):
        self.pipe.handle_register_entity(Message(
            str(SpecMessage.ENTITY_REGISTER),
            {"entity_name": "genre", "samples": ["jazz"], "lang": "en-US"}))
        self.assertIsNone(self._values())

    def test_the_manifest_keeps_one_row_per_skill_and_name(self):
        _register(self.pipe, ["jazz"])
        _register(self.pipe, ["rock"])
        rows = [v for v in self.pipe.registered_vocab
                if v.get("entity_type") == "genre"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_value"], ["rock"])

    def test_another_language_is_untouched(self):
        self.pipe = _pipeline(("en-US", "pt-PT"))
        _register(self.pipe, ["jazz"], lang="en-US")
        _register(self.pipe, ["jazz"], lang="pt-PT")
        _register(self.pipe, ["rock"], lang="en-US")
        self.assertEqual(self._values(lang="pt-PT"), ["jazz"])


if __name__ == "__main__":
    unittest.main()
