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
    'asyncpg>=0.30.0',
    'bcrypt>=4.2.0',
    'fastjsonschema>=2.19.1',
    'heaven>=0.4.1',
    'httpx>=0.27.0',
    'jinja2>=3.1.2',
    'orjson>=3.8.5',
    'pydantic>=2.0.0',
    'pyjwt>=2.0.0',
    'python-dotenv>=1.0.0',
    'redis>=5.0.0',
    'uvicorn>=0.20.0',
]


def get_version():
    init = open(os.path.join(ROOT, 'amebo', '__init__.py')).read()
    return VERSION_RE.search(init).group(1)


def entry_points():
    return {
        'console_scripts': [
            'amebo = amebo:execute',
        ]
    }


setup(
    name='amebo',
    version=get_version(),
    description="HTTP Event Notifications Server - Asynchronous Communication Engine",
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    author='Raymond Ortserga',
    author_email='codesage@live.com',
    url='https://github.com/rayattack/amebo',
    scripts=[],
    packages=find_packages(exclude=['tests*']),
    package_data={
        'amebo': [
            'amebo.sh',
            'templates/*.html',
            'templates/*.axml',
            'public/*.css',
            'public/*.js',
            'public/*.webp',
            'public/icons/*',
            'database/*.py',
            'models/*.py',
            'utils/*.py',
        ],
    },
    include_package_data=True,
    install_requires=requires,
    license="MIT",
    python_requires=">= 3.8",
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Internet :: WWW/HTTP :: HTTP Servers',
        'Topic :: System :: Distributed Computing',
    ],
    keywords='event-driven microservices webhooks pubsub notifications',
    project_urls={
        'Documentation': 'https://rayattack.github.io/amebo/',
        'Source': 'https://github.com/rayattack/amebo',
        'Bug Reports': 'https://github.com/rayattack/amebo/issues',
        'Docker Hub': 'https://hub.docker.com/r/rayattack/amebo',
    },
    entry_points=entry_points()
)
