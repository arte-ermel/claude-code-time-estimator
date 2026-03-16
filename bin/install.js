#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const os = require('os');

const SKILL_NAME = 'universal-time-estimator';
const SKILL_DIR = path.join(os.homedir(), '.claude', 'skills', SKILL_NAME);
const PACKAGE_SKILL_DIR = path.join(__dirname, '..', 'skill');

const CYAN = '\x1b[36m';
const GREEN = '\x1b[32m';
const YELLOW = '\x1b[33m';
const RED = '\x1b[31m';
const DIM = '\x1b[2m';
const BOLD = '\x1b[1m';
const RESET = '\x1b[0m';

function copyDirRecursive(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDirRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function install() {
  const isUpdate = fs.existsSync(SKILL_DIR);

  console.log('');
  console.log(`${CYAN}${BOLD}  Claude Code Time Estimator${RESET}`);
  console.log(`${DIM}  Self-correcting task time estimation skill${RESET}`);
  console.log('');

  if (isUpdate) {
    console.log(`${YELLOW}  Updating existing installation...${RESET}`);
  } else {
    console.log(`  Installing skill to ${DIM}${SKILL_DIR}${RESET}`);
  }

  try {
    copyDirRecursive(PACKAGE_SKILL_DIR, SKILL_DIR);

    console.log('');
    console.log(`${GREEN}  ${BOLD}Installed successfully!${RESET}`);
    console.log('');
    console.log(`  ${BOLD}Location:${RESET}  ${DIM}${SKILL_DIR}${RESET}`);
    console.log(`  ${BOLD}Data file:${RESET} ${DIM}~/.claude/universal_time_log.jsonl${RESET}`);
    console.log('');
    console.log(`  ${BOLD}Usage in Claude Code:${RESET}`);
    console.log(`  ${DIM}  "How long will it take to build a checkout page?"${RESET}`);
    console.log(`  ${DIM}  "Log time: that took 45 minutes"${RESET}`);
    console.log(`  ${DIM}  "Show my estimation calibration stats"${RESET}`);
    console.log(`  ${DIM}  "How much time did I spend on ProjectX this week?"${RESET}`);
    console.log('');
    console.log(`  ${DIM}Your time log data is stored locally and never shared.${RESET}`);
    console.log('');
  } catch (err) {
    console.error(`${RED}  Installation failed: ${err.message}${RESET}`);
    process.exit(1);
  }
}

function uninstall() {
  console.log('');
  console.log(`${CYAN}${BOLD}  Claude Code Time Estimator${RESET}`);
  console.log('');

  if (!fs.existsSync(SKILL_DIR)) {
    console.log(`${YELLOW}  Skill is not installed.${RESET}`);
    console.log('');
    return;
  }

  try {
    fs.rmSync(SKILL_DIR, { recursive: true, force: true });
    console.log(`${GREEN}  Skill removed from ${DIM}${SKILL_DIR}${RESET}`);
    console.log('');
    console.log(`  ${DIM}Your time log data at ~/.claude/universal_time_log.jsonl was NOT deleted.${RESET}`);
    console.log(`  ${DIM}Delete it manually if you no longer need your historical data.${RESET}`);
    console.log('');
  } catch (err) {
    console.error(`${RED}  Uninstall failed: ${err.message}${RESET}`);
    process.exit(1);
  }
}

// Parse args
const args = process.argv.slice(2);
if (args.includes('--uninstall') || args.includes('uninstall')) {
  uninstall();
} else if (args.includes('--help') || args.includes('-h')) {
  console.log('');
  console.log(`${CYAN}${BOLD}  Claude Code Time Estimator${RESET}`);
  console.log('');
  console.log('  Usage:');
  console.log(`    ${DIM}npx claude-code-time-estimator${RESET}              Install the skill`);
  console.log(`    ${DIM}npx claude-code-time-estimator --uninstall${RESET}  Remove the skill`);
  console.log(`    ${DIM}npx claude-code-time-estimator --help${RESET}       Show this help`);
  console.log('');
} else {
  install();
}
