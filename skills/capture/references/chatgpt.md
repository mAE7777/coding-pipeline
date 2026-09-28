# Getting a ChatGPT conversation out without losing anything

## Best: the data export (lossless)
ChatGPT: Settings → Data controls → Export data. An email arrives with a zip (the link expires after about
a day); inside is `conversations.json`, every chat as a message tree, so edited messages and regenerated
answers are kept (as branches), plus a `chat.html` viewer. Voice-mode turns appear as ChatGPT's own
transcription (`audio_transcription` parts); OpenAI notes these transcripts are not verbatim records, so capture
labels them "owner (transcribed)" and the dossier attributes them as `transcribed`. Checked 2026-09-27 against
current export guides (tactiq.io, ai-toolbox.co, sonix.ai); re-check when the menu changes. Import one chat:

    capture.py add <project> conversations.json --chat "<part of the chat's title>"

`capture.py list conversations.json` shows every chat with its turn count. When the chat grows, export again
and import again: only the new turns are added.

## Quick: copy the chat
Select the whole conversation in the ChatGPT window, copy, and paste it into a text file (it keeps the
"You said:" and "ChatGPT said:" markers), then `capture.py add <project> <file.txt>`. This loses edited and
regenerated branches and any images; use the export when those matter.

## Not used: share links
A shared-chat link is rendered by the page's scripts and is not read as a source; export or copy instead.

## Optional: instructions for a ChatGPT Project
Paste this once into the Project's instructions so every chat in it is easy to capture faithfully:

    When you answer, keep what I said and what you suggest clearly apart: never restate my view in words I
    did not use, and mark your own ideas as suggestions. When I change my mind, say what changed from what.
    When I say "checkpoint", list, without judging them: what I have decided, what I have said I am unsure
    about, what you suggested that I have not taken up, and the open questions, each with my exact words
    where they exist.

A checkpoint list is a reading aid for the owner; the dossier is still built from the transcript itself.
