import numpy as np
import pandas as pd


def clean(v):
    """numpy/pandas scalars -> plain Python; NaN/NaT/NA -> None."""
    if v is None:
        return None
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and np.isnan(v):
        return None
    if v is pd.NaT or v is pd.NA:
        return None
    return v


if __name__ == "__main__":

    pass

