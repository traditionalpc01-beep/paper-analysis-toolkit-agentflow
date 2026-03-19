from __future__ import annotations

import warnings

warnings.filterwarnings(
    "ignore",
    message=r".*urllib3 .* doesn't match a supported version!.*",
)

__version__ = "0.1.0"
__all__ = ["__version__"]
