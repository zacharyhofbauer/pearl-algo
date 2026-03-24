#!/usr/bin/env node
/**
 * Node.js equivalent of browser prompt() - paste this and run: node prompt-demo.js
 */
const readline = require('readline');

const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

function prompt(question) {
  return new Promise((resolve) => {
    rl.question(question, (answer) => {
      resolve(answer);
    });
  });
}

(async () => {
  const answer = await prompt('Enter something: ');
  console.log('You entered:', answer);
  rl.close();
})();
