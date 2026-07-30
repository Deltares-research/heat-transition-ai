from src import download_pdfs

if __name__ == "__main__":


    path = "../data/input/Overzicht gemeenten met warmteprogramma v01 juli 2026 (zonder contactpersonen).xlsx"
    out_path = "../data"

    download_pdfs(path, out_path, to_md=True)
