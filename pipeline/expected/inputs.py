"""Step 4 inputs: the FEC's federal-elections workbooks; the MEDSL precinct directories.

fetch_fec(year, raw_dir) saves the year's xlsx through pipeline.fetch.fetch (project user agent, raw body
and manifest row saved before anything reads it, TLS verification on) under source id
fec-<year>-federalelections. medsl_dir(year) gives the MEDSL directory for a year. Where each input came
from is in inputs.toml.
"""
import glob
import os
import tomllib

from pipeline.fetch import fetch

CONFIG = os.path.join(os.path.dirname(__file__), "inputs.toml")


def config():
    with open(CONFIG, "rb") as f:
        return tomllib.load(f)


def fetch_fec(year, raw_dir, opener=None):
    url = config()["fec"][str(year)]
    return fetch(f"fec-{year}-federalelections", url, 0, raw_dir=raw_dir, opener=opener, ext="xlsx")


def latest_fec(year, raw_dir):
    """The newest saved FEC workbook for a year (fetch names files by UTC timestamp)."""
    paths = sorted(glob.glob(os.path.join(raw_dir, f"fec-{year}-federalelections", "*.xlsx")))
    if not paths:
        raise FileNotFoundError(f"no FEC {year} workbook under {raw_dir}; run `fetch` first")
    return paths[-1]


def medsl_paths(year):
    """Every MEDSL zip for a year (2022: one per state; 2018: one per office group), sorted."""
    return sorted(glob.glob(os.path.join(config()["medsl"][str(year)], "**", "*.zip"), recursive=True))
