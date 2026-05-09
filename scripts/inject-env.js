const fs = require("fs");
const path = require("path");

const webDir = path.join(__dirname, "..", "web");
const replacements = {
  "__NM_API_BASE__": process.env.NM_API_BASE || "https://api.beta.meshnet.co",
  "__NM_SUPABASE_URL__": process.env.NM_SUPABASE_URL || "",
  "__NM_SUPABASE_ANON_KEY__": process.env.NM_SUPABASE_ANON_KEY || "",
};

for (const filename of fs.readdirSync(webDir)) {
  if (!filename.endsWith(".html")) {
    continue;
  }

  const filepath = path.join(webDir, filename);
  let content = fs.readFileSync(filepath, "utf8");
  for (const [placeholder, value] of Object.entries(replacements)) {
    content = content.split(placeholder).join(value);
  }
  fs.writeFileSync(filepath, content);
}

console.log(`Injected beta web env into ${webDir}`);
