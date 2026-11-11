<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>

# Run and deploy your AI Studio app

This contains everything you need to run your app locally.

View your app in AI Studio: https://ai.studio/apps/drive/1IbWPEYarD73WJgVnAdHdomUulEs3YV5-

## Run Locally

**Prerequisites:**  Node.js


1. Install dependencies:
   `npm install`
2. Configure AI credentials on the backend using `VEE_GEMINI_API_KEYS`, or sign in
   as Owner and use Settings → API → AI provider. Do not put provider secrets in
   frontend `VITE_*` variables. AI features use authenticated backend requests.
3. Run the app:
   `npm run dev`

The development frontend runs at `http://localhost:7300` and proxies `/api` to
`http://localhost:7211` by default. Local presence/chat uses `http://localhost:7212`.
The Docker frontend also publishes port 7300.
