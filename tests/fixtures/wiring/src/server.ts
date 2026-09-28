import express from "express";
import Anthropic from "@anthropic-ai/sdk";

const app = express();
const client = new Anthropic();

app.get("/lists", async (req, res) => {
  res.json([]);
});

app.post("/lists/share", async (req, res) => {
  const reply = await client.messages.create({ model: "m", max_tokens: 10, messages: [] });
  bus.emit("list:shared", reply);
  res.json({ ok: true });
});

bus.on("list:shared", () => {});
