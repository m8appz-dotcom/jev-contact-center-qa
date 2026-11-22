import path from "node:path";
import { fileURLToPath } from "node:url";
import { writeFileSync } from "node:fs";
import { execute, inputError } from "./process.mjs";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export default {
  name: "JEV Contact Center QA",
  actions: ["evaluate"],
  protectedActions: ["evaluate"],
  status: async () => ({
    available: !!process.env.TYPESAFE_API_KEY,
    capabilities: ["JEV live evaluation", "Weighted scoring", "Review queue"],
    model: "jev-latest",
  }),
  async run(action, data, { directory }) {
    if (typeof data.id !== "string" || !/^MINI-[123]$/.test(data.id))
      throw inputError("Choose one of the authored example conversations.");
    if (!process.env.TYPESAFE_API_KEY)
      throw Object.assign(new Error("Missing JEV configuration"), {
        code: "provider_not_configured",
        userMessage:
          "JEV is not connected in this copy. Your manual review remains available.",
      });
    // Only committed authored conversations leave this example workspace; arbitrary private transcripts are rejected.
    const { conversations } = await import("./public/data.js");
    const c = conversations.find((c) => c.id === data.id);
    const result = await execute(
      process.env.DEMO_PYTHON || "python",
      ["-B", path.join(root, "demo/engine_runner.py")],
      {
        id: c.id,
        text: c.turns.map((t) => t.join(": ")).join("\n"),
        names: [c.agent],
      },
      { cwd: root, timeout: 90000 },
    );
    const file = path.join(directory, "qa-evaluation.json");
    writeFileSync(file, JSON.stringify(result, null, 2));
    return {
      result,
      files: [
        { name: "qa-evaluation.json", path: file, mime: "application/json" },
      ],
    };
  },
};
