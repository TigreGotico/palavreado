"""The language-distance boundary used to pick an intent container."""
import unittest
from unittest.mock import Mock

from palavreado.opm import PalavreadoPipeline

MACROLANGUAGE_PAIRS = [("arz", "ar"), ("wuu", "zh")]
REGIONAL_PAIRS = [("ar-SA", "ar"), ("en-AU", "en-GB"), ("pt-BR", "pt-PT")]
UNRELATED_PAIRS = [("en", "zh"), ("es", "fr"), ("fr-CH", "de-CH"), ("af", "nl")]


def _resolve(requested: str, available: str):
    pipeline = PalavreadoPipeline.__new__(PalavreadoPipeline)
    pipeline.containers = {available: Mock()}
    return PalavreadoPipeline._resolve_lang(pipeline, requested)


class TestResolveLangBoundary(unittest.TestCase):

    def test_macrolanguage_container_is_selected(self):
        for member, macro in MACROLANGUAGE_PAIRS:
            with self.subTest(member=member):
                self.assertEqual(_resolve(member, macro), macro)

    def test_regional_container_is_selected(self):
        for requested, available in REGIONAL_PAIRS:
            with self.subTest(requested=requested):
                self.assertEqual(_resolve(requested, available), available)

    def test_unrelated_container_is_rejected(self):
        for requested, available in UNRELATED_PAIRS:
            with self.subTest(requested=requested):
                self.assertIsNone(_resolve(requested, available))


if __name__ == "__main__":
    unittest.main()
