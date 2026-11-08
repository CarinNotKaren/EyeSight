# EyeSight VLM Answer Generation

## Configuration

The backend uses Hugging Face Inference Providers for the default VLM.

Add these values to the local `.env` file in `backend/`:

```dotenv
HF_TOKEN=hf_your_token_here
VLM_MODEL=Qwen/Qwen2.5-VL-3B-Instruct
HF_INFERENCE_ENDPOINT_URL=
```

- `HF_TOKEN` must be a Hugging Face token allowed to call Inference Providers.
- `VLM_MODEL` selects the model. The default is Qwen2.5-VL-3B-Instruct.
- `HF_INFERENCE_ENDPOINT_URL` is optional. Set it when using a separately deployed model endpoint, for example a deployment of SmolVLM2-2.2B-Instruct.

The EyeSight model plan lists Qwen2.5-VL 3B and SmolVLM2 2.2B as comparison candidates. The default hosted integration uses Qwen because it is listed for Hugging Face Inference Providers. The official SmolVLM2 model card currently does not list an Inference Provider deployment, so use a dedicated endpoint for that candidate.

Install the added client dependency from the backend directory:

```powershell
pip install "huggingface_hub>=0.34.0"
```

## Request flow

### Voice question

1. Create a question with `POST /api/questions/`.
2. Member 1 submits the transcription with `PATCH /api/questions/{question_id}/transcription`.
3. The backend calls Member 2's existing `search_frames` implementation.
4. The backend loads up to three unexpired retrieved images from `storage/frames`.
5. The images and question are sent to the configured VLM.
6. The answer and its evidence references are saved.
7. The question status becomes `completed`.

### Text question

1. Create a question with `POST /api/questions/` and `input_type: "text"`.
2. Start processing with `POST /api/questions/{question_id}/process`.
3. The same retrieval, VLM, and persistence flow runs.

### Read the result

- `GET /api/questions/{question_id}/answer` returns the saved answer.
- `GET /api/questions/{question_id}/answer/evidence` returns the frame IDs, retrieval ranks, retrieval method, similarity scores, and whether the frames were included in the VLM request.

The evidence endpoint does not expose local storage paths or image bytes.

## Answer classifications

- `grounded`: the model reports that the answer is clearly supported by the frames.
- `uncertain`: the model reports incomplete or ambiguous visual evidence, or returns unstructured text.
- `no_evidence`: no unexpired retrieved images are available.
- `error_fallback`: the VLM cannot be reached; a safe fallback response is stored.

The service stores model ID, prompt version, retrieval latency, generation latency, total latency, answer text, and evidence references in the existing database tables. No new database migration is required.

## Privacy note

Retrieved camera images are sent to the configured Hugging Face inference service when a VLM request is made. Configure the provider and token in accordance with the project's consent and data-handling requirements. Only the top three retrieved frames are sent.
