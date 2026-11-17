## Object detection evaluation — 17 November 2026

Model: YOLO26n, CPU, image size 640.

Three photos and one blank image were tested.

At confidence threshold 0.35:
- People photo: detected both foreground people and one tie.
- Room photo: detected the couch and two chairs. Missed the coffee
  table and a small partially visible chair.
- Dark desk photo: detected the laptop and its built-in keyboard.
  Missed a dark bottle and cup.
- Blank image: no detections.
- Measured warm detection times were 0.11–0.25 seconds per photo.

At confidence threshold 0.25:
- Added a dining-table prediction around the coffee table, score 0.327.
- Incorrectly labelled the glass lamp as a vase, score 0.344.
- Blank image still produced no detections.

The default remains 0.35 pending evaluation on more images.
These observations are a small qualitative test, not a measured
overall accuracy percentage.