"""Train the Taxi Grouper pairwise ML model."""

from __future__ import annotations

import argparse

from src.core.ml_model import train_from_folder, train_model_from_historique_excel


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train taxi grouping model from historical or corrected Excel files.")
    parser.add_argument("--file", help="Historique.xlsx file with repeated headers and monthly sheets")
    parser.add_argument("--data", help="Folder containing simple corrected training Excel files")
    parser.add_argument("--output", default="models", help="Folder where model files will be saved")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.file:
        metrics = train_model_from_historique_excel(args.file, args.output)
        print(f"Accuracy:       {metrics['accuracy']:.3f}")
        print(f"Precision:      {metrics['precision']:.3f}")
        print(f"Recall:         {metrics['recall']:.3f}")
        print(f"F1-score:       {metrics['f1_score']:.3f}")
        print(f"Agents:         {metrics['number_of_agents']}")
        print(f"Pair examples:  {metrics['number_of_pair_examples']}")
        print(f"Positive pairs: {metrics['positive_pairs']}")
        print(f"Negative pairs: {metrics['negative_pairs']}")
        return
    if args.data:
        metrics = train_from_folder(args.data, args.output)
        print(f"Accuracy:  {metrics['accuracy']:.3f}")
        print(f"Precision: {metrics['precision']:.3f}")
        print(f"Recall:    {metrics['recall']:.3f}")
        print(f"F1-score:  {metrics['f1']:.3f}")
        return
    raise SystemExit("Use --file Historique.xlsx or --data data/corrected/")


if __name__ == "__main__":
    main()
