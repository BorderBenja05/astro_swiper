#!/usr/bin/env python3
"""Plot the FITS image triplet for a given ZTF objectId from MongoDB."""

import sys
import io
import gzip

import numpy as np
from astropy.io import fits
from astropy.visualization import ZScaleInterval
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from pymongo import MongoClient

MONGO_URI = "mongodb://readonly:qabhyk-tuzJeq-fegju6@localhost:27016/boom?authSource=boom"
DB_NAME = "boom"


def get_cutouts(object_id: str):
    """Look up the alert _id by objectId, then fetch the matching cutouts."""
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    alert = db.ZTF_alerts.find_one({"objectId": object_id}, {"_id": 1})
    if alert is None:
        sys.exit(f"No alert found for objectId '{object_id}'")

    cutout_doc = db.ZTF_alerts_cutouts.find_one({"_id": alert["_id"]})
    client.close()

    if cutout_doc is None:
        sys.exit(f"No cutouts found for _id {alert['_id']} (objectId '{object_id}')")

    return cutout_doc


def binary_to_image(raw_bytes):
    """Decompress gzipped FITS binary and return the image array."""
    decompressed = gzip.decompress(bytes(raw_bytes))
    hdul = fits.open(io.BytesIO(decompressed))
    data = np.nan_to_num(hdul[0].data)
    hdul.close()
    return data


def plot_triplet(object_id: str):
    doc = get_cutouts(object_id)

    zscale = ZScaleInterval()
    panels = [
        ("Science",    doc["cutoutScience"]),
        ("Difference", doc["cutoutDifference"]),
        ("Template",   doc["cutoutTemplate"]),
    ]

    fig = plt.figure(figsize=(21, 7), facecolor="black")
    gs = gridspec.GridSpec(1, 3, wspace=0.02)

    for i, (title, raw) in enumerate(panels):
        img = zscale(binary_to_image(raw))
        ax = fig.add_subplot(gs[i])
        ax.set_title(title, fontsize=16, color="white")
        ax.axis("off")
        ax.imshow(img, cmap="gray", origin="lower")

    fig.suptitle(object_id, fontsize=20, color="white", y=1.02)
    plt.tight_layout(pad=0.4)
    plt.savefig(f"{object_id}.png", bbox_inches="tight", facecolor="black", dpi=150)
    plt.show()
    print(f"Saved to {object_id}.png")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"Usage: python {sys.argv[0]} <objectId>")
    plot_triplet(sys.argv[1])
