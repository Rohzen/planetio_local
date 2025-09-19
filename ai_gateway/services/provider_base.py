class ProviderBase(object):
    def __init__(self, env):
        self.env = env

    def generate(self, prompt, **kwargs):
        raise NotImplementedError()

    def summarize_chunks(self, chunks, system_instruction=None, **kwargs):
        raise NotImplementedError()
