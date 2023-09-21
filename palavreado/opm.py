from ovos_plugin_manager.templates.pipeline import IntentPipelinePlugin, IntentMatch, RegexEntityDefinition
from ovos_utils import classproperty

from palavreado import IntentContainer, IntentCreator


def _munge(name, skill_id):
    return f"{name}:{skill_id}"


def _unmunge(munged):
    return munged.split(":", 2)


class PalavreadoPipelinePlugin(IntentPipelinePlugin):

    def __init__(self, bus, config=None):
        super().__init__(bus, config)
        self.engines = {}  # lang: IntentContainer

    # plugin api
    @classproperty
    def matcher_id(self):
        return "palavreado"

    def match(self, utterances, lang, message):
        for utt in utterances:
            return self.calc_intent(utt, lang=lang)

    def train(self):
        # update intents with registered samples
        for lang in self.engines:
            for intent in (e for e in self.registered_intents if e.lang == lang):
                munged = _munge(intent.name, intent.skill_id)
                intent_builder = IntentCreator(munged)

                for entity in (e for e in self.registered_entities
                               if e.lang == lang and e.skill_id == intent.skill_id):
                    munged_ent = _munge(entity.name, intent.skill_id)

                    if isinstance(entity, RegexEntityDefinition):
                        intent_builder.regexes[munged_ent] = entity.samples
                    elif entity.name in intent.required:
                        intent_builder.required[munged_ent] = entity.samples
                    elif entity.name in intent.optional:
                        intent_builder.optional[munged_ent] = entity.samples

                self.engines[lang].add_intent(intent_builder)

    # implementation
    def _get_engine(self, lang=None):
        lang = lang or self.lang
        if lang not in self.engines:
            self.engines[lang] = IntentContainer()
        self.train()
        return self.engines[lang]

    def detach_intent(self, skill_id, intent_name):
        munged = _munge(intent_name, skill_id)
        for lang in self.engines:
            if munged in self.engines[lang].registered_intents:
                self.engines[lang].registered_intents.remove(munged)
        super().detach_intent(intent_name)

    def calc_intent(self, utterance, min_conf=0.0, lang=None):
        lang = lang or self.lang
        engine = self._get_engine(lang)

        intent = engine.calc_intent(utterance)
        if intent.get("conf") > min_conf:
            intent_type, skill_id = _unmunge(intent["name"])

            return IntentMatch(intent_service=self.matcher_id,
                               intent_type=intent_type,
                               intent_data=intent,
                               confidence=intent["conf"],
                               utterance=utterance,
                               utterance_remainder=intent["utterance_remainder"],
                               skill_id=skill_id)

        return None
