# EyeSight multimedia integration

Run all terminal commands from the backend directory.

## Setup

Activate the backend virtual environment, then install dependencies:

```powershell
python -m pip install -r requirements.txt
python -m pip check
```

Configure the database connection in the local backend `.env` file.

Apply database migrations using the team's agreed procedure.
The authentication migration branches previously conflicted, so confirm
the migration procedure with the backend owner.

OCR, YOLO, and CLIP may download their models on first use.
Model downloads and initial loading increase startup time.

Images and frame records are local data. Pushing code to GitHub does
not copy them into another teammate's MySQL database or image storage.

## Save a camera frame

```python
from multimedia.camera_frame_storage import save_camera_frame
```

The backend must authenticate the request and verify that the signed-in
user owns the capture session before calling this function.

The session must exist, be active, and have unexpired history.

For a fresh image captured for a current question:

```python
frame_id = save_camera_frame(session_id, image_bytes)
```

For background images collected for visual history:

```python
frame_id = save_camera_frame(
    session_id,
    image_bytes,
    select_for_history=True,
)
```

Inputs:

- `session_id` is a positive integer.
- `image_bytes` contains a JPEG or PNG image.
- `select_for_history` defaults to `False`.

Returns:

- An integer frame ID when an image is saved.
- `None` when history selection skips a low-quality or duplicate image.

History selection uses the existing quality and similarity functions.
Default thresholds are sharpness 50, brightness 25, and duplicate
difference 0.02.

Invalid images and unavailable capture sessions raise `ValueError`.
Database and filesystem errors can also propagate.

Saved frames start with processing status `pending`.

Capture time currently uses the server's intake timestamp.
Frame expiry is capped by the session's frame retention duration and
history expiry.

The function stores the original image bytes under `storage/frames/camera`.

Repeated uploads can create separate frames when history selection is
disabled. Request idempotency is not implemented.

If a database commit has an uncertain outcome, the image file is retained.
Unregistered files may require separate reconciliation.

## Process a saved frame

```python
from multimedia.frame_pipeline import process_frame

if frame_id is not None:
    result = process_frame(frame_id)
```

The pipeline runs OCR, object detection, and image embedding.

| Returned status | Meaning |
|---|---|
| `ready` | All three stages completed |
| `partial` | Some stages completed and others failed |
| `failed` | All stages failed |
| `skipped` | The frame was unavailable or already being processed |

Zero OCR regions or zero detected objects can be valid completed results.

Stage results are recorded in `processing_details`.
Finalization updates the frame status and pipeline metadata status.

Retries rerun all three stages.

Ctrl+C records an interrupted run as `partial` or `failed` when the
database is available, then propagates the interruption.

Forced termination or database outages can leave a frame marked
`processing`. Manual recovery is available through `multimedia.frame_recovery`
after the affected workers have stopped and the database is available.
See the recovery section below.

Processing is synchronous. The backend integration must arrange how
processing is scheduled and how the mobile app learns it has finished.

Process all eligible frames in a session from the terminal:

```powershell
python -m multimedia.frame_pipeline --session SESSION_ID
```

Replace `SESSION_ID` with the numeric session ID.

## OCR languages

The supported reader selections are:

- `en` for English.
- `fr` for French.
- `ar` for Arabic.

The pipeline selects the reader using the capture session's language.

An explicit OCR override is available:

```python
from multimedia.ocr_storage import process_frame_ocr

regions = process_frame_ocr(frame_id, language="ar")
```

The selected reader and its configuration are saved with model metadata.

Reader selection does not automatically identify the language of every
text region. Mixed-language processing needs further work.

The default minimum recognition confidence is 0.80.
The maximum OCR image dimension is 1280.
Text polygons are mapped back to original image coordinates.

## Retrieve frames

```python
from multimedia.frame_retrieval import search_frames
```

Retrieve an exact frame within its session:

```python
frames = search_frames(
    session_id=session_id,
    frame_id=frame_id,
)
```

Search recognized text:

```python
frames = search_frames(
    session_id=session_id,
    ocr_text="ROOM 204",
)
```

Filter by an object label:

```python
frames = search_frames(
    session_id=session_id,
    object_label="couch",
)
```

Rank frames by semantic similarity:

```python
frames = search_frames(
    session_id=session_id,
    query="a person near a couch",
    top_k=3,
)
```

Optional time filters are `captured_from` and `captured_to`.
They accept Python datetime values. Aware datetimes are converted to UTC.

Results contain the frame ID, internal storage key, capture timestamp,
and similarity score. OCR matches also contain `matched_texts`.

Nonsemantic retrieval returns `similarity=None`.

Retrieval excludes expired frames and expired session histories.
Overall frame status must be `ready` or `partial`.
Each search filter uses its corresponding current completed stage.

An empty list means no eligible matching frame was found.

The API must verify session ownership before retrieval.
Storage keys are internal backend paths.

English, French, and Arabic OCR text retrieval has been tested.
French and Arabic semantic question retrieval still needs validation.

## Mobile and question API integration

The intended current-image flow is:

1. Start an authorized active capture session.
2. Upload the camera image with the access token and session ID.
3. Verify session ownership in the backend.
4. Save the image and keep its returned frame ID.
5. Process the frame and check completion.
6. Include the frame ID when creating the current-image question.
7. Retrieve the answer and play it through the mobile voice flow.

The existing question evidence service supports exact-frame retrieval
and semantic history retrieval.

A saved-image question through retrieval and Gemini has been tested.
The complete Expo camera upload and spoken-answer flow remains pending.

Session creation, authenticated upload routes, processing scheduling,
and mobile completion handling need coordination with the backend and
mobile owners.

## Retention cleanup

Preview expired frames:

```powershell
python -m multimedia.retention_cleanup
```

Delete expired frame files, known previews, and linked records:

```powershell
python -m multimedia.retention_cleanup --apply
```

Run periodic cleanup:

```powershell
python -m multimedia.retention_worker
```

Automatic worker startup with the backend remains to be connected.

Cleanup handles registered expired frames and known preview filenames.
Unregistered files and arbitrary preview names need separate handling.

## Verified local behavior

- Camera image saved with a pending frame record.
- Clear history image retained.
- Duplicate and dark history images skipped.
- Empty and corrupt images rejected.
- Upload to an ended session rejected.
- OCR, object detection, and embedding stages completed.
- Failed stage produced partial status.
- Normal retry produced ready status.
- Ctrl+C saved interruption metadata and allowed a retry.
- Final frame and pipeline status fields agreed.
- OCR retrieval found an uploaded frame.
- Retrieval excluded a frame after simulated expiry.
- Three-language OCR text survived MySQL storage and retrieval.
- Expired-frame cleanup removed registered images and linked records.

## Object detection evaluation - 17 November 2026

Model: YOLO26n, CPU, image size 640.

Three photos and one blank image were tested.

At confidence threshold 0.35:

- People photo: detected both foreground people and one tie.
- Room photo: detected the couch and two chairs. Missed the coffee
  table and a small partially visible chair.
- Dark desk photo: detected the laptop and its built-in keyboard.
  Missed a dark bottle and cup.
- Blank image: no detections.
- Measured warm detection times were 0.11 to 0.25 seconds per photo.

At confidence threshold 0.25:

- Added a dining-table prediction around the coffee table, score 0.327.
- Incorrectly labelled the glass lamp as a vase, score 0.344.
- Blank image still produced no detections.

The default remains 0.35. Additional comparisons and the decision
are recorded below.
These observations are a small qualitative test, not a measured
overall accuracy percentage.

## Remaining validation and improvements

- Complete Expo upload, processing, question, and spoken-answer flow.
- Smaller text and mixed-language scenes.
- Broader detection and retrieval evaluation across images and videos.
- OCR speed and full pipeline performance.
- Forced termination and database outage recovery.
- Concurrent uploads and cleanup during processing.
- Automatic cleanup worker startup.

A temporary OCR limit of 640 improved some large-image timings.
Further accuracy evaluation is needed before changing the default.

## Recover an interrupted processing run

If a frame remains marked `processing` after a worker exits:

1. Stop the worker responsible for that frame.
2. Inspect the frame's pipeline run ID in MySQL.
3. Preview recovery using that exact run ID.
4. Apply recovery, then retry processing.

Preview:

```powershell
python -m multimedia.frame_recovery --frame FRAME_ID --run-id RUN_ID
```

Apply after stopping the affected workers:

```powershell
python -m multimedia.frame_recovery --frame FRAME_ID --run-id RUN_ID --apply --workers-stopped
```

Replace FRAME_ID and RUN_ID with the actual values.

Recovery checks the frame status, run ID, frame expiry, and session expiry.
It marks the frame failed so the normal pipeline can retry it.

The workers-stopped flag is operator confirmation. The tool does not
detect whether a worker is alive.

Verified using a simulated worker exit:
- Existing processing claim blocked a normal run.
- Wrong run ID was rejected without changing the claim.
- Preview preserved the processing state.
- Recovery updated both status fields.
- A retry completed with a new run ID and ready status.

Actual forced process termination and database outage scenarios still
need validation.

Manual recovery is available through multimedia.frame_recovery after
the affected workers have stopped. Database availability is required.

## Additional detection evaluation and storage verification

Date: 17 November 2026.

Seven distinct photos were evaluated across the experiments, with a
plain white image used as a negative check.

Decision: retain YOLO26n on CPU, image size 640, confidence threshold 0.35.
YOLO26s and image size 1280 were tested separately; application settings
were not changed by these experiments.

### Additional three-photo comparison

Both models used image size 640 and confidence threshold 0.35.

| Photo | YOLO26n | YOLO26s |
|---|---|---|
| cup_bottle.jpg | Correct bottle, cup and laptop | Correct bottle and laptop; cup labelled bottle; red zippered item labelled book |
| people_new.jpg | Correctly detected all three people | Correctly detected all three people |
| furniture.jpg | Detected main seats, TV, plant and vase; missed both tables; cut flowers labelled potted plant | Similar main detections and missed tables; cut flowers labelled potted plant; duplicate vase prediction |

The furniture image includes a cropped foreground seat. Its couch
prediction was not treated as a duplicate of the main sofa.

YOLO26n warm average times on these three photos were 0.049 to 0.071
seconds. YOLO26s times were 0.294 to 0.350 seconds in separate runs.
These are local observations, not controlled hardware benchmarks.

Lowering confidence to 0.25 previously added both useful predictions
and incorrect labels. Raising it to 0.50 would also discard some
correct detections observed in these tests.

All tested white-image checks produced zero detections. This does not
establish a general false-positive rate.

These are qualitative observations, not an overall accuracy percentage.
The detector can miss important objects and produce incorrect labels.
Answer generation should select relevant information for the question
and account for uncertainty. No main-object ranking or storage cap
was added by these experiments.

### Real-photo processing and object retrieval

Local test session 20, frame 51, used cup_bottle.jpg:

- Camera upload created a frame successfully.
- All three pipeline stages completed with overall status ready.
- OCR saved 10 regions; their text accuracy was not assessed in this test.
- Object detection saved one bottle, one laptop and one cup.
- Model metadata confirmed YOLO26n, image size 640 and threshold 0.35.
- Saved confidence values and normalized boxes passed validation.
- Image embedding completed with 512 dimensions.
- Returned, frame and pipeline metadata statuses agreed.
- Cup, bottle and laptop searches each returned the uploaded frame.
- Uppercase CUP also matched.
- An exact-frame search under another session returned no result.
- The new test session was ended afterward.

This verifies the local upload, processing, database and object-search
flow for this photo. It does not verify authenticated HTTP endpoints,
user ownership checks, mobile upload or spoken-answer integration.

## OCR and semantic-query updates - 17 November 2026

Current OCR models:
- Detector: PP-OCRv5_mobile_det.
- English: en_PP-OCRv5_mobile_rec.
- French: latin_PP-OCRv5_mobile_rec.
- Arabic: arabic_PP-OCRv5_mobile_rec.
- Confidence remains 0.80; maximum image dimension remains 1280.
- MKL-DNN remains disabled; no explicit CPU-thread override was adopted.

All three sign fixtures matched their reference text at original size,
25 percent dimensions and 30 percent brightness. Blank images returned
no accepted text. These controlled tests do not establish general accuracy.

Frames 52, 53 and 54 passed full processing, model-metadata checks,
saved-text checks, repeated processing and OCR retrieval.

Repeated full-pipeline times were:
- English: 2.10 seconds.
- French: 2.23 seconds.
- Arabic: 2.09 seconds.

The first English pipeline run took 31.91 seconds and included initial
model loading. Later language runs reused YOLO and CLIP.

Mobile OCR on the real bottle photo took 8.09 seconds warm, compared
with about 64-66 seconds for the previous medium models. It returned
fewer accepted regions and still missed the complete bottle name.
The faster configuration has an accuracy tradeoff on this scene.

The semantic_query.py helper preserves the original question and
prepares an English query for CLIP. English bypasses translation;
French and Arabic use text-only Gemini requests.

The caller must load the backend environment. GEMINI_API_KEY is required
for translation. SEMANTIC_QUERY_MODEL overrides VLM_MODEL; one model
setting must be explicitly configured.

Translation failures raise QueryTranslationError without silent fallback.
Translation adds API usage and measured 1.57-3.77 seconds in this test.

On three scenes, correct top-ranked images were:
- Direct CLIP: English 3/3, French 2/3, Arabic 1/3.
- With query preparation: English 3/3, French 3/3, Arabic 3/3.

These are small-sample ranking results, not overall accuracy percentages.
One Arabic translation narrowed "chairs" to "armchairs"; translation
meaning still needs broader evaluation.

The helper is NOT connected to assistant/evidence_service.py yet.
The backend owner should use its search_query for semantic-history
retrieval, preserve the original question and preparation metadata,
and handle translation failures. Exact-frame retrieval needs no translation.

Install test dependencies with:
python -m pip install -r requirements-test.txt

Run offline helper tests with:
python -m pytest tests/test_semantic_query.py -q

Ten tests passed for validation, English bypass, original-question
preservation, language normalization, model selection, missing credentials
and propagation of translation failures.

Database-backed translated retrieval, real forced termination,
database outages and concurrent operations remain to be checked.
