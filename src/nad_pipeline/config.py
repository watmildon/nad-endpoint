"""Paths and constants shared by the pipeline stages."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("NAD_DATA_DIR", REPO_ROOT / "data"))
DOWNLOAD_DIR = DATA_DIR / "downloads"

# Socrata view of the NAD text file on the USDOT open data portal.
VIEW_ID = "fc2s-wawr"
PORTAL = "https://data.transportation.gov"

# Column order of the NAD text file as of r24. Ingest fails if the header differs,
# so a schema change in a new release is noticed instead of silently mis-mapped.
NAD_COLUMNS = [
    "OID_", "AddNum_Pre", "Add_Number", "AddNum_Suf", "AddNo_Full",
    "St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep", "St_Name",
    "St_PosTyp", "St_PosDir", "St_PosMod", "StNam_Full",
    "Building", "Floor", "Unit", "Room", "Seat", "Addtl_Loc", "SubAddress",
    "LandmkName", "County", "Inc_Muni", "Post_City", "Census_Plc",
    "Uninc_Comm", "Nbrhd_Comm", "NatAmArea", "NatAmSub", "Urbnztn_PR",
    "PlaceOther", "PlaceNmTyp", "State", "Zip_Code", "Plus_4", "UUID",
    "AddAuth", "AddrRefSys", "Longitude", "Latitude", "NatGrid", "Elevation",
    "Placement", "AddrPoint", "Related_ID", "RelateType", "ParcelSrc",
    "Parcel_ID", "AddrClass", "Lifecycle", "Effective", "Expire",
    "DateUpdate", "AnomStatus", "LocatnDesc", "Addr_Type", "DeliverTyp",
    "NAD_Source", "DataSet_ID",
]


def release_dir(release: str) -> Path:
    return DATA_DIR / release
