import os
import re
import subprocess

from packaging.version import Version
from setuptools import find_packages, setup


def get_saline_version():
    cwd = os.getcwd()
    m = re.search(r"saline-(\d{4}\.\d{2}\.\d{2})", cwd)
    if m:
        return m[1]
    file_date = subprocess.check_output(
        "find . -type f -printf '%AY.%Am.%Ad\n' | sort -r | head -n 1",
        shell=True,
    )
    file_date = file_date.decode()[:-1]
    if file_date:
        return file_date
    # Fallback to some default value if not possible to calculate
    return "2024.01.16"


setup(
    name="saline",
    url="https://github.com/openSUSE/saline",
    description="The salt event collector and manager",
    author="Victor Zhestkov",
    author_email="vzhestkov@gmail.com",
    version=str(Version(get_saline_version())),
    packages=find_packages(),
    license="Apache-2.0",
    scripts=["salined"],
)
