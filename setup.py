#!/usr/bin/env python

"""
distutils/setuptools install script.
"""
import os
import re

from setuptools import find_packages, setup

ROOT = os.path.dirname(__file__)
VERSION_RE = re.compile(r'''__version__ = ['"]([0-9.]+)['"]''')


requires = [
    'fastjsonschema>=2.19.1',
    'orjson>=3.8.5',
    'jinja2>=3.1.2',
    'routerling>=0.5.1',
    'pydantic>=1.10.4',
    'httpx>=0.23.3',
]


def get_version():
    init = open(os.path.join(ROOT, 'amebo', '__init__.py')).read()
    return VERSION_RE.search(init).group(1)


setup(
    name='amebo',
    version=get_version(),
    description="The PubSub Server You've always Wanted",
    long_description=open('README.md').read(),
    author='Tersoo',
    url='https://github.com/tersoo/amebo',
    scripts=[],
    packages=find_packages(exclude=['tests*']),
    install_requires=requires,
    license="Apache License 2.0",
    python_requires=">= 3.7",
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
    project_urls={
        'Documentation': 'https://github.com/tersoo/amebo',
        'Source': 'https://github.com/tersoo/amebo',
    },
)
