# Image testing rules

- Accepted MIME types: image/jpeg, image/png, image/webp.
- Transcode SVG, BMP, and HEIC before encoding.
- For animated images, use frame 1 only.
- Resize before encoding and avoid multi-megabyte base64 payloads.
- Do not send blank or solid-colour images.