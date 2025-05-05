from operations.decal_merge import DecalMerge
from core.parsers.vpk_file import VPKFile

def test_decal_merger():
    merger = DecalMerge(working_dir="temp/vtf_files")
    sprite_sheet_path = "backup/materials/decals/decals_mod2x.png"

    decal_vtfs = {
        "decal/blood1": "blood_test/materials/decals/blood1.vtf",
        "decal/blood2": "blood_test/materials/decals/blood2.vtf",
        "decal/blood3": "blood_test/materials/decals/blood3.vtf",
        "decal/blood4": "blood_test/materials/decals/blood4.vtf",
        "decal/blood5": "blood_test/materials/decals/blood5.vtf",
        "decal/blood6": "blood_test/materials/decals/blood6.vtf",
        # "decal/flesh/blood1": "blood_test/materials/decals/flesh/blood1.vtf",
        # "decal/flesh/blood2": "blood_test/materials/decals/flesh/blood2.vtf",
        # "decal/flesh/blood3": "blood_test/materials/decals/flesh/blood3.vtf",
        # "decal/flesh/blood4": "blood_test/materials/decals/flesh/blood4.vtf",
        # "decal/flesh/blood5": "blood_test/materials/decals/flesh/blood5.vtf"
    }

    # sprite sheet
    merger.modify_mod2x_sprite_sheet(decal_vtfs, sprite_sheet_path)



if __name__ == "__main__":
    VPKFile.create("backup/tf2_misc", "backup/tf2_misc")