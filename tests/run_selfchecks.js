const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const testDirectory = __dirname;
const selfChecks = fs.readdirSync(testDirectory)
    .filter(file => file.endsWith('_selfcheck.js'))
    .sort((left, right) => left.localeCompare(right, 'en'));

if (selfChecks.length === 0) {
    console.error('Không tìm thấy frontend self-check nào.');
    process.exitCode = 1;
} else {
    const failures = [];

    for (const file of selfChecks) {
        console.log(`\n=== ${file} ===`);
        const result = spawnSync(process.execPath, [path.join(testDirectory, file)], {
            cwd: path.resolve(testDirectory, '..'),
            stdio: 'inherit',
        });

        if (result.error) {
            console.error(result.error.message);
            failures.push(file);
        } else if (result.status !== 0) {
            failures.push(file);
        }
    }

    console.log(`\nFrontend self-checks: ${selfChecks.length - failures.length}/${selfChecks.length} passed.`);
    if (failures.length > 0) {
        console.error(`Failed: ${failures.join(', ')}`);
        process.exitCode = 1;
    }
}
