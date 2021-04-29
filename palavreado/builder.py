import simplematch as sm
from palavreado.bracket_expansion import expand_parentheses


def pattern2regex(pattern, case_sensitive=False):
    matcher = sm.Matcher(pattern, case_sensitive=case_sensitive)
    return matcher.regex  # -> the generated regex


def expand_samples(samples):
    if isinstance(samples, str):
        samples = [samples]
    expanded = []
    for l in samples:
        expanded += expand_parentheses(l)
    return expanded


class IntentCreator:
    def __init__(self, name):
        self.name = name
        self.required = {}
        self.optional = {}
        self.regexes = {}

    def require(self, keyword_name, keyword_samples):
        if keyword_name not in self.required:
            self.required[keyword_name] = []
        keyword_samples = expand_samples(keyword_samples)
        self.required[keyword_name] += keyword_samples
        return self

    def optionally(self, keyword_name, keyword_samples):
        if keyword_name not in self.optional:
            self.optional[keyword_name] = []
        keyword_samples = expand_samples(keyword_samples)
        self.optional[keyword_name] += keyword_samples
        return self

    def require_regex(self, keyword_name, keyword_samples):
        if keyword_name not in self.required:
            self.required[keyword_name] = []
        keyword_samples = expand_samples(keyword_samples)
        if keyword_name not in self.regexes:
            self.regexes[keyword_name] = []
        self.regexes[keyword_name] += keyword_samples
        return self

    def optional_regex(self, keyword_name, keyword_samples):
        if keyword_name not in self.optional:
            self.optional[keyword_name] = []
        keyword_samples = expand_samples(keyword_samples)
        if keyword_name not in self.regexes:
            self.regexes[keyword_name] = []
        self.regexes[keyword_name] += keyword_samples
        return self

    def require_autoregex(self, keyword_name, keyword_samples,
                          case_sensitive=False):
        if keyword_name not in self.required:
            self.required[keyword_name] = []
        keyword_samples = expand_samples(keyword_samples)
        keyword_samples = [pattern2regex(s, case_sensitive)
                           for s in keyword_samples]
        if keyword_name not in self.regexes:
            self.regexes[keyword_name] = []
        self.regexes[keyword_name] += keyword_samples
        return self

    def optional_autoregex(self, keyword_name, keyword_samples,
                           case_sensitive=False):
        if keyword_name not in self.optional:
            self.optional[keyword_name] = []
        keyword_samples = expand_samples(keyword_samples)
        keyword_samples = [pattern2regex(s, case_sensitive)
                           for s in keyword_samples]
        if keyword_name not in self.regexes:
            self.regexes[keyword_name] = []
        self.regexes[keyword_name] += keyword_samples
        return self

    def build(self):
        return {
            "intent_name": self.name,
            "required": self.required,
            "optional": self.optional,
            "regex": self.regexes
        }
