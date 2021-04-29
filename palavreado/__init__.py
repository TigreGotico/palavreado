import re
import logging
from palavreado.bracket_expansion import expand_parentheses
from palavreado.builder import IntentCreator
from quebra_frases.chunks import chunk
from quebra_frases import word_tokenize, get_exclusive_tokens, flatten

LOG = logging.getLogger('palavreado')


def get_utterance_remainder(utterance, samples, as_string=True):
    chunks = flatten([word_tokenize(s) for s in samples])
    words = [t for t in word_tokenize(utterance) if t not in chunks]
    if as_string:
        return " ".join(words)
    return words


class IntentContainer:
    def __init__(self):
        self.intents = {}

    # build with IntentCreator
    def add_intent(self, intent):
        if isinstance(intent, IntentCreator):
            intent = intent.build()
        self.intents[intent["intent_name"]] = intent

    def remove_intent(self, name):
        if isinstance(name, IntentCreator):
            name = name.build()
        if isinstance(name, dict):
            name = name["name"]
        if name in self.intents:
            del self.intents[name]

    # intent api
    def calc_intents(self, query):

        def _match(kw_samples):
            # HACK around chunk function limitations
            plurals = [w for w in kw_samples if
                       w.endswith("s")]
            kw_samples = [w for w in kw_samples
                          if not w.endswith("s") and
                          w + "s" not in query]
            chunked = chunk(query, kw_samples)
            chunked2 = chunk(query, plurals)
            return [c for c in chunked if c in kw_samples] + \
                   [c for c in chunked2 if c in plurals]

        for intent_name, intent in self.intents.items():
            if not len(intent["required"]):
                continue
            remainder = query
            conf = 0.0
            partial_conf = 1.0 / len(intent["required"])
            partial_opt_conf = 0.15 / (len(intent["optional"]) + 0.0001)
            matches = {}

            # match regex keywords
            for kw, kw_samples in intent["regex"].items():
                if not kw_samples:
                    continue
                kw_samples = sorted(kw_samples, key=len, reverse=True)
                for rx in kw_samples:
                    flags = re.IGNORECASE
                    regex_compiled = re.compile(rx, flags=flags)
                    match = regex_compiled.match(query)
                    if match:
                        result = match.groupdict()

                        remainder = get_utterance_remainder(remainder,
                                                            [kw] + list(
                                                                result.values()))

                        for k, v in result.items():
                            if k not in matches:
                                matches[k] = []
                            matches[k].append(v)
                            if k not in intent["required"] and \
                                    k not in intent["optional"]:
                                conf += partial_opt_conf * 0.2
                        break
                    else:
                        kws = re.findall(rx, query)
                        if kws:
                            matches[kw] = kws
                            remainder = get_utterance_remainder(remainder,
                                                                kws)
                            break

                if kw in intent["required"] and kw in matches:
                    conf += (partial_conf * 0.9) / len(matches)
                elif kw in intent["optional"] and kw in matches:
                    conf += (partial_opt_conf * 0.9) / len(matches)

            # match required keywords
            for kw, kw_samples in intent["required"].items():
                if not kw_samples:
                    continue
                if query in kw_samples:
                    matches[kw] = [query]
                    conf += partial_conf
                    remainder = ""
                else:
                    kws = _match(kw_samples)
                    if kws:
                        matches[kw] = kws
                        conf += partial_conf
                        remainder = get_utterance_remainder(remainder, kws)
                        if remainder in kws:
                            remainder = ""

            # match optional keywords
            if intent["optional"]:
                for kw, kw_samples in intent["optional"].items():
                    if not kw_samples:
                        continue
                    if query in kw_samples:
                        matches[kw] = [query]
                        conf += partial_opt_conf
                        remainder = ""
                    else:
                        kws = _match(kw_samples)
                        if kws:
                            matches[kw] = kws
                            conf += partial_opt_conf
                            remainder = get_utterance_remainder(remainder,
                                                                kws)
                            if remainder in kws:
                                remainder = ""

            # weight down based on length of utterance remainder
            if len(query):
                ratio = len(remainder) / len(query)
                ratio = ratio * 0.1

                # normalize score
                conf = max(0.0, conf - ratio)
            conf = min(1.0, conf)

            if conf > 0:
                yield {"keywords": matches,
                       "conf": conf,
                       "utterance_remainder": remainder,
                       "utterance": query,
                       "name": intent_name}

    def calc_intent(self, query):
        return max(
            self.calc_intents(query),
            key=lambda x: x["conf"],
            default={'name': None, 'keywords': {}, "conf": 0,
                     "utterance": query, "utterance_remainder": query}
        )
