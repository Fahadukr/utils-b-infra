from setuptools import setup, find_packages

with open('README.md', 'r') as fh:
    long_description = fh.read()
    long_description = long_description.split('## Changelog')[0]
with open('CHANGELOG.md', 'r') as ch:
    long_description += "\n\n" + ch.read()

setup(
    name="utils_b_infra",
    version="1.3.15",
    author="Fahad Mawlood",
    author_email="fahadukr@gmail.com",
    description="A collection of utility functions and classes for Python projects.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Fahadukr/utils-b-infra",
    packages=find_packages(),
    install_requires=[
        "SQLAlchemy",
        "pandas",
        "numpy < 2.0.0",
        "openai >= 1.74.0",
        "redis",
        "pymongo",
        "pendulum",
        "slack-sdk",
        "tiktoken",
        "google-api-python-client",
        "google-auth-httplib2",
        "google-auth-oauthlib",
        "Pillow",
        "pdf2image",
        "pydub"
    ],
    extras_require={
        'translation': [
            "google-cloud-translate >= 3.12.0",
            "deepl"
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.10',
)
