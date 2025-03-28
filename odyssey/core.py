"""Core functions for import, formatting, and exporting SPSS data."""

# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/00_core.ipynb.

# %% auto 0
__all__ = ['Metadata', 'unpack_variable_types', 'reformat_metadata', 'read_sav', 'Dataset', 'read_and_filter_data',
           'combine_dataframes', 'merge_dictionaries', 'convert_metadata_list_to_dict', 'pack_variable_types',
           'write_sav']

# %% ../nbs/00_core.ipynb 4
import pandas as pd
import polars as pl
from polars.testing import assert_frame_equal
import numpy as np
import pyreadstat
import pyspssio
from pathlib import Path
from typing import Optional, Any
from rich import print as rprint

from fastcore.utils import *
from fastcore.test import *

from pydantic import BaseModel
from pydantic.dataclasses import dataclass
# from pandera import ...

# %% ../nbs/00_core.ipynb 6
# TODO: convert to Pydantic BaseModel (ensure that variable types are one of "nominal", "scale" or "ordinal")
@dataclass
class Metadata:
    variable_basename: str
    label: str
    field_values: dict[int, str]
    field_type: str
    field_width: int
    decimals: int
    variable_type: str

# %% ../nbs/00_core.ipynb 9
def unpack_variable_types(input_dict):
    "..."
    field_type = {}
    decimals = {}
    
    for key, value in input_dict.items():
        if value.startswith('F'):
            field_type[key] = 'Numeric'
            dec = value.split('.')[1]
            decimals[key] = int(dec) if dec != '0' else 0
        elif value.startswith(('EDATE', 'DATE')):
            field_type[key] = 'Date'
            decimals[key] = 0
        elif value.startswith('A'):
            field_type[key] = 'String'
            decimals[key] = 0
    
    return field_type, decimals

def reformat_metadata(m: pyreadstat.metadata_container, # metadata from pyreadstat
                     ) -> dict[dict[str, Any]]:
    "Reformat metadata into a more readable and consistent format"
    field_type, decimals = unpack_variable_types(m.original_variable_types)
    metadata = {
        "Label": m.column_names_to_labels,
        "Field Type": field_type,
        "Field Width": m.variable_display_width,
        "Decimals": decimals,
        "Variable Type": m.variable_measure,
        "Field Values": m.variable_value_labels
    }
    return metadata

# %% ../nbs/00_core.ipynb 11
def read_sav(data_dir: str|Path, 
             file: str, 
             cols: Optional[list[str]] = None
             ) -> pl.LazyFrame:
    df, meta = pyreadstat.read_sav(f"{data_dir}/{file}", usecols=cols)
    df = pl.from_pandas(df).lazy()
    return df, meta

# %% ../nbs/00_core.ipynb 12
@dataclass
class Dataset:
    file: str
    data_dir: str | Path
    prefix: Optional[str] = None
    variables: Optional[list[str]] = None

    def load_data(self) -> tuple[pl.LazyFrame, dict[dict[str, Any]]]:
        "Output data and metadata."
        df, meta = read_sav(self.data_dir, self.file, self.variables)
        meta = reformat_metadata(meta)
        return df, meta
    
        # def strip_prefix(self, df: pl.LazyFrame) -> pl.DataFrame:
    #     stripped_columns = {col: col.replace(self.prefix, "") for col in self.variables}
    #     df = df.rename(stripped_columns)
    #     return df

# %% ../nbs/00_core.ipynb 15
def read_and_filter_data(datasets: list[Dataset]
                         ) -> list[pl.LazyFrame]:
    """
    Take a list of `Dataset`s and return a list of the respective dataframes 
    and metadata for each dataset, filtered for the given columns.
    """
    dataframes = []
    metadata = []
    for ds in datasets:
        df, meta = ds.load_data()
        dataframes.append(df)
        metadata.append(meta)
    return dataframes, metadata

def combine_dataframes(dataframes: list[pl.LazyFrame]
                       ) -> pl.LazyFrame:
    "Take a list of dataframes and return a single, combined dataframe."
    combined_df = dataframes[0]
    for df in dataframes[1:]:
        combined_df = combined_df.join(df, on="ID", how="full", coalesce=True)
    return combined_df

# %% ../nbs/00_core.ipynb 17
from collections import defaultdict
from copy import deepcopy

# %% ../nbs/00_core.ipynb 18
def merge_dictionaries(dicts: list[dict[str, Any]]
                       ) -> dict[str, Any]:
    "Merge a series of nested dictionaries."
    merged_dict = defaultdict(dict)
    for d in dicts:
        # Create a deep copy to avoid mutating original data
        d_copy = deepcopy(d)
        for key, nested_dict in d_copy.items():
            for nested_key, value in nested_dict.items():
                if nested_key not in merged_dict[key]:
                    merged_dict[key][nested_key] = value
    return dict(merged_dict)

# %% ../nbs/00_core.ipynb 21
def convert_metadata_list_to_dict(metadata: list[Metadata], # list of Metadata objects
                                  p: str # Prefix for dataset
                                  ) -> dict[dict[str, Any]]:
    """
    Take a list of Metadata objects and convert them into the SPSS format
    with parameters as parents and variables as children, in nested dictionaries.
    """
    converted_metadata = {
        "Label": {p + m.variable_basename: m.label for m in metadata},
        "Field Values": {p + m.variable_basename: m.field_values for m in metadata},
        "Field Type": {p + m.variable_basename: m.field_type for m in metadata},
        "Field Width": {p + m.variable_basename: m.field_width for m in metadata},
        "Decimals": {p + m.variable_basename: m.decimals for m in metadata},
        "Variable Type": {p + m.variable_basename: m.variable_type for m in metadata},
    }
    return converted_metadata

# %% ../nbs/00_core.ipynb 22
import warnings

# %% ../nbs/00_core.ipynb 23
def pack_variable_types(m: dict[str, dict[str, Any]], # metadata in nested dictionary format
                        ) -> dict[str, str]:
    """
    Convert metadata parameters related to variable format 
    into an appropriate schema for pyreadstat.
    """
    field_type = m["Field Type"]
    field_width = m["Field Width"]
    decimals = m["Decimals"]
    
    combined_types = _combine_dicts(field_type, field_width, decimals)

    return _pack_variable_types(combined_types)

def _combine_dicts(ft: dict[str, str], 
                   fw: dict[str, int], 
                   d: dict[str, int],
                   warn: bool = True
                   ) -> dict[str, tuple[Any, Any, Any]]:
    """
    Combine three dictionaries into one, with shared keys and tuple values, 
    and raise warnings for non-shared keys.
    """
    # Find the intersection of keys
    shared_keys = set(ft.keys()) & set(fw.keys()) & set(d.keys())
    
    # Find keys that are not shared across all dictionaries
    all_keys = set(ft.keys()) | set(fw.keys()) | set(d.keys())
    non_shared_keys = all_keys - shared_keys
    
    # Raise warnings for non-shared keys
    if non_shared_keys and warn:
        warnings.warn(f"Keys not shared across all dictionaries: {non_shared_keys}")
    
    # Map for field types
    field_type = {
        "Numeric": "F",
        "String": "A",
        "Date": "DATE"
    }

    # Construct the output dictionary
    combined_dict = {key: (field_type.get(ft[key]), fw[key], d[key]) for key in shared_keys}
    
    return combined_dict
    
def _pack_variable_types(data: dict[str, tuple[str, int, int]]
                         ) -> dict[str, str]:
    """Private function to perform the logic for `pack_variable_types`."""
    d = {}
    
    for var, values in data.items():
        f_type, f_width, dec = values
        
        if f_type == "F" and dec > 0:
            d[var] = f"{f_type}{f_width}.{dec}"
        else:
            d[var] = f"{f_type}{f_width}"

    return d

# %% ../nbs/00_core.ipynb 25
# TODO: could be actual Data and Metadata class/types
def write_sav(dst_path: str|Path, # path to save output file
              df: pl.LazyFrame, # raw data
              metadata: dict[str, dict[str, Any]] # corresponding metadata
              ) -> None:
    """Save dataset to SPSS using `pyreadstat` library."""
    # Convert 
    df = df.collect().to_pandas()

    pyreadstat.write_sav(
        df, 
        dst_path,
        column_labels=metadata["Label"],
        variable_value_labels=metadata["Field Values"],
        variable_display_width=metadata["Field Width"],
        variable_measure=metadata["Variable Type"], # TODO: convert to all lowercase
        variable_format=pack_variable_types(metadata),
        row_compress=True
    )
