# 🎙️ Channel Brain – Setup Guide

A tool to index any YouTube channel's transcripts and ask questions across all content.

---

## What You'll Need

- A computer (Mac or Windows)
- ~20 minutes for setup (one-time only)
- Two free API keys (instructions below)

---

## Step 1: Install Python

If you don't have Python installed:

1. Go to **https://www.python.org/downloads/**
2. Download Python 3.11 or later
3. Run the installer — check **"Add Python to PATH"** before clicking Install

To verify, open Terminal (Mac) or Command Prompt (Windows) and type:
```
python --version
```
You should see something like `Python 3.11.x`

---

## Step 2: Get a YouTube Data API Key (Free)

1. Go to **https://console.cloud.google.com/**
2. Sign in with your Google account
3. Click **"Select a project"** → **"New Project"** → name it anything → **Create**
4. In the left menu, go to **APIs & Services → Library**
5. Search for **"YouTube Data API v3"** → click it → click **Enable**
6. Go to **APIs & Services → Credentials**
7. Click **"+ Create Credentials"** → **"API Key"**
8. Copy the key that appears — save it somewhere safe

> 💡 The free tier gives you 10,000 units/day. Indexing a 100-video channel uses ~200 units. You won't get charged.

---

## Step 3: Get an Anthropic API Key

1. Go to **https://console.anthropic.com/**
2. Sign up for a free account
3. Go to **API Keys** → **Create Key**
4. Copy the key

> 💡 Anthropic gives new accounts $5 free credits. Querying a 100-video index costs about $0.01 per question.

---

## Step 4: Set Up the Project

Open **Terminal** (Mac: press Cmd+Space, type "Terminal") or **Command Prompt** (Windows: press Win+R, type "cmd").

### Navigate to the project folder
```bash
cd path/to/youtube_channel_qa
```
(Replace `path/to/` with wherever you saved the downloaded files)

### Install dependencies
```bash
pip install -r requirements.txt
```
This installs everything needed. Takes 2–5 minutes the first time.

---

## Step 5: Run the App

In the same terminal window:
```bash
streamlit run app.py
```

Your browser will automatically open to **http://localhost:8501**

---

## Step 6: Use the App

1. **Enter your API keys** in the left sidebar
2. **Paste a YouTube channel URL**, e.g.:
   ```
   https://www.youtube.com/@thekoerneroffice
   ```
3. Choose how many videos to index (start with 20–30 to test)
4. Click **⚡ Build Index** — this takes a few minutes
5. Once done, **ask questions** in the chat box!

### Example questions to try:
- "What are the best side hustle ideas mentioned across all episodes?"
- "What advice do they give for people just starting out?"
- "Which episodes talk about e-commerce or Amazon FBA?"
- "What are the most common themes across the channel?"
- "Summarize the top 5 business ideas with the most potential"

---

## Saving & Reloading Indexes

After indexing a channel, it's saved to the `indexes/` folder. Next time you open the app, use **"Load Existing Index"** in the sidebar — no need to re-fetch everything.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `pip` not found | Use `pip3` instead of `pip` |
| `ModuleNotFoundError` | Re-run `pip install -r requirements.txt` |
| YouTube API quota error | Wait 24 hours (free quota resets daily) |
| "No transcript found" | That video has captions disabled — it gets skipped automatically |
| App won't open in browser | Go to http://localhost:8501 manually |

---

## Folder Structure

```
youtube_channel_qa/
├── app.py              ← Main Streamlit UI
├── indexer.py          ← Fetches videos + builds vector index  
├── qa.py               ← Handles Q&A with Claude
├── requirements.txt    ← Python dependencies
├── SETUP.md            ← This file
└── indexes/            ← Created automatically when you index a channel
    ├── ChannelName.json       ← Index metadata
    └── ChannelName_db/        ← ChromaDB vector database
```

---

## Cost Summary

| Item | Cost |
|---|---|
| YouTube Data API | **Free** (10k units/day) |
| Transcript fetching | **Free** |
| Embedding model (sentence-transformers) | **Free** (runs locally) |
| Claude API (asking questions) | ~$0.01 per question |
| ChromaDB (vector storage) | **Free** (local) |

**Total to index + query a 100-video channel: ~$0.10–$0.50**
