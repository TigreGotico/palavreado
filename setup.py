from setuptools import setup

PLUGIN_ENTRY_POINT = 'ovos-intent-plugin-nebulento=nebulento.opm:NebulentoPipelinePlugin'


setup(
    name='palavreado',
    version='0.2.0',
    packages=['palavreado'],
    url='https://github.com/OpenJarbas/palavreado',
    license='apache-2.0',
    author='jarbasai',
    author_email='jarbasai@mailfence.com',
    install_requires=["simplematch", "quebra_frases"],
    description='dead simple keyword based intent parser',
    entry_points={'ovos.pipeline': PLUGIN_ENTRY_POINT}
)
