#!/usr/bin/env python3
"""ContentEngine CLI — AI-powered short-form video pipeline."""
import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="ContentEngine: AI-powered short-form video pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py video.mp4 --clips 3 --platforms tiktok instagram
  python main.py video.mp4 --clips 5 --mode REVIEW --creator @username
        """
    )
    parser.add_argument("source", help="Path to video file")
    parser.add_argument("--clips", "-n", type=int, default=3,
                        help="Number of clips to generate (default: 3)")
    parser.add_argument("--platforms", "-p", nargs="+",
                        choices=["tiktok", "instagram", "youtube"],
                        default=["tiktok", "instagram"],
                        help="Target platforms")
    parser.add_argument("--mode", "-m",
                        choices=["MANUAL", "REVIEW", "AUTO"],
                        default="REVIEW",
                        help="Operating mode (default: REVIEW)")
    parser.add_argument("--creator", default="unknown",
                        help="Creator handle or name")
    parser.add_argument("--content-type", default="educational",
                        help="Content type (educational, entertainment, etc)")
    parser.add_argument("--whisper-model",
                        choices=["tiny", "base", "small", "medium"],
                        default="base",
                        help="Whisper model size (default: base)")

    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        print(f"Error: File not found: {args.source}")
        sys.exit(1)

    from engine.config import CONFIG
    CONFIG.mode = args.mode
    CONFIG.target_clips = args.clips
    CONFIG.whisper_model = args.whisper_model

    from engine.pipeline import process_video

    result = process_video(
        source=str(source.resolve()),
        number_of_clips=args.clips,
        target_platforms=args.platforms,
        creator=args.creator,
        content_type=args.content_type,
    )

    print(f"\nDone. {result['stats']['clips_generated']} clips generated.")
    print(f"  PUBLISH={result['stats']['publish']}  "
          f"REVIEW={result['stats']['review']}  "
          f"REJECT={result['stats']['reject']}")


if __name__ == "__main__":
    main()
