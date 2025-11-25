from pathlib import Path

from pearlalgo.data.loaders import load_csv


def test_load_csv_strips_and_sets_index(tmp_path: Path):
    sample = tmp_path / "sample.csv"
    sample.write_text("Date, open , high , low , close , volume , Unnamed: 6\n2024-01-01 09:30,1,2,0.5,1.5,1000,\n")
    df = load_csv(sample)
    assert "Open" in df.columns
    assert df.index.name == "Date"
