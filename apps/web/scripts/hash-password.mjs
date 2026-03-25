#!/usr/bin/env node

import { randomBytes, scryptSync } from "node:crypto";

function usage() {
  console.error("Usage: node apps/web/scripts/hash-password.mjs '<password>'");
  console.error("   or: printf '%s' '<password>' | node apps/web/scripts/hash-password.mjs");
}

async function readPassword() {
  const cliPassword = process.argv[2];
  if (cliPassword) {
    return cliPassword;
  }

  if (!process.stdin.isTTY) {
    const chunks = [];
    for await (const chunk of process.stdin) {
      chunks.push(chunk);
    }
    const stdinPassword = Buffer.concat(chunks).toString("utf8").replace(/\r?\n$/, "");
    if (stdinPassword) {
      return stdinPassword;
    }
  }

  usage();
  process.exit(1);
}

const password = await readPassword();
const salt = randomBytes(16);
const digest = scryptSync(password, salt, 64, {
  N: 16384,
  r: 8,
  p: 1
});

process.stdout.write(`scrypt$${salt.toString("hex")}$${digest.toString("hex")}\n`);
