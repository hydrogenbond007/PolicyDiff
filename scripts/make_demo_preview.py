"""Compose checked demo recordings and actual report counts into a README GIF."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output must be a new file')
    import imageio.v2 as imageio
    from PIL import Image, ImageDraw, ImageFont
    root = args.run
    recording = json.loads((root / 'replay/recordings.json').read_text())
    receipts = recording['recordings']
    progress = json.loads((root / 'evaluation/progress.json').read_text())['results']
    report = json.loads((root / 'evaluation/comparison/report.json').read_text())
    if ([row['arm'] for row in receipts] != ['baseline', 'candidate', 'retest'] or
            [row['arm'] for row in progress] != ['baseline', 'candidate', 'retest'] or
            recording['plan_sha256'] != hashlib.sha256((root / 'evaluation/plan.json').read_bytes()).hexdigest()):
        raise ValueError('need all three demo arms')
    font_path = Path('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf')
    font = lambda size: ImageFont.truetype(str(font_path), size) if font_path.exists() else ImageFont.load_default()
    title_font, label_font, small_font = font(20), font(15), font(13)
    readers, frames = [], []
    try:
        for row, result in zip(receipts, progress):
            video = root / 'replay' / row['file']
            if hashlib.sha256(video.read_bytes()).hexdigest() != row['sha256'] or not (
                    row['reset_matches'] and row['per_step_success_matches']):
                raise ValueError('recording verification failed')
            if row['steps_checked'] != result['steps'] or row['frames'] != result['steps'] + 1:
                raise ValueError('recording length differs from executed trace')
            reader = imageio.get_reader(video)
            readers.append(reader)
            if reader.count_frames() != row['frames']:
                raise ValueError('decoded frame count differs from receipt')
        for step in range(0, max(row['frames'] for row in receipts), 20):
            frame = Image.new('RGB', (792, 392), '#101826')
            draw = ImageDraw.Draw(frame)
            draw.text((16, 10), 'PolicyDiff  /  one paired LIBERO start', font=title_font, fill='white')
            for i, (reader, row, result) in enumerate(zip(readers, receipts, progress)):
                x = 8 + i * 264
                label = ('Scripted baseline', 'Gripper disabled', 'Unchanged retest')[i]
                color = '#f7b267' if i == 1 else '#6ed9b5'
                draw.text((x + 6, 44), label, font=label_font, fill=color)
                index = min(step, row['frames'] - 1)
                view = Image.fromarray(reader.get_data(index)).resize((256, 256))
                frame.paste(view, (x, 68))
                done = step >= result['steps']
                state = ('SUCCESS' if result['success'] else 'NO SUCCESS') if done else 'running'
                draw.text((x + 4, 330), f'{state} | step {index}', font=small_font, fill=color)
            counts = report['observed_totals']
            draw.text((14, 352), f"Actual report: {counts['lost']} lost  /  {counts['gained']} gained  /  "
                      f"{counts['unresolved']} unresolved | retest losses: "
                      f"{report['slices'][0]['unchanged_retest']['churn_losses']}", font=small_font, fill='white')
            draw.text((14, 374), 'Intentional system fault, not learned weights | 5x control-time replay | ended arms held',
                      font=small_font, fill='#a9bbcc')
            frames.append(frame)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('xb') as handle:
            frames[0].save(handle, format='GIF', save_all=True, append_images=frames[1:],
                           duration=200, loop=0, optimize=True)
    finally:
        for reader in readers:
            reader.close()
    print(args.output)


if __name__ == '__main__':
    main()
