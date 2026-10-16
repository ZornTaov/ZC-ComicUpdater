const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const { test } = require("node:test");

const root = resolve(__dirname, "../..");
const read = path => readFileSync(resolve(root, path), "utf8");
const dockerfiles = ["Dockerfile", "reader/Dockerfile"];
const workflows = [".github/workflows/images.yml", ".github/workflows/pr-images.yml"];

function stages(path) {
  return read(path).replace(/\\\r?\n\s*/g, " ").split(/^FROM /m).slice(1).map(stage => {
    const [from, ...lines] = stage.split("\n");
    return { from, instructions: lines.filter(line => line && !line.startsWith("#")) };
  });
}

function imageJob(path) {
  return read(path).match(/^  image:\n([\s\S]*?)(?=^  \w+:|$(?![\s\S]))/m)[1];
}

function before(instructions, first, second) {
  const a = instructions.findIndex(line => line.includes(first));
  const b = instructions.findIndex(line => line.includes(second));
  assert.ok(a >= 0 && b >= 0 && a < b, `${first} must precede ${second}`);
}

for (const path of dockerfiles) {
  test(`${path}: Python dependencies are independent of system packages and application code`, () => {
    const all = stages(path);
    const deps = all.find(stage => stage.from.endsWith(" AS python-deps"));
    const final = all.at(-1);
    assert.equal(deps.from.replace(" AS python-deps", ""), final.from);
    assert.equal(deps.instructions.filter(line => line.startsWith("COPY ")).length, 1);
    assert.match(deps.instructions.join("\n"), /COPY .*requirements\.txt \/build\/requirements\.txt/);
    assert.match(deps.instructions.join("\n"), /RUN --mount=type=cache,target=\/root\/\.cache\/pip,sharing=locked\s+pip install --prefix=\/install -r \/build\/requirements\.txt/);
    assert.doesNotMatch(deps.instructions.join("\n"), /apt-get|--no-cache-dir/);
    assert.ok(final.instructions.includes("COPY --link --from=python-deps /install/ /usr/local/"));
    assert.doesNotMatch(final.instructions.join("\n"), /pip install/);
  });

  test(`${path}: application copies are independent linked layers with no subsequent RUN`, () => {
    const final = stages(path).at(-1).instructions;
    const copies = final.filter(line => line.startsWith("COPY "));
    assert.ok(copies.length > 0);
    assert.ok(copies.every(line => line.startsWith("COPY --link ")));
    assert.ok(final.findLastIndex(line => line.startsWith("RUN ")) < final.findIndex(line => line.startsWith("COPY ")));
    assert.doesNotMatch(copies.join("\n"), /COPY (?:--link )?\. /);
  });
}

test("updater: apt downloads survive cache export but stay out of the runtime layers", () => {
  const final = stages("Dockerfile").at(-1).instructions;
  const apt = final.find(line => line.includes("apt-get install"));
  for (const target of ["/var/cache/apt", "/var/lib/apt/lists"]) {
    assert.ok(apt.includes(`--mount=type=cache,target=${target},sharing=locked`));
  }
  assert.ok(apt.includes("rm -f /etc/apt/apt.conf.d/docker-clean"));
  assert.doesNotMatch(apt, /rm -rf \/var\/(?:lib|cache)\/apt/);
  for (const dependency of ["chromium", "chromium-driver", "git", "tzdata", "ca-certificates"]) {
    assert.ok(apt.split(/\s+/).includes(dependency));
  }
});

test("reader: static assets build natively with lockfile-first npm caching", () => {
  const [web] = stages("reader/Dockerfile");
  assert.equal(web.from, "--platform=$BUILDPLATFORM node:22-slim AS web");
  before(web.instructions, "reader/web/package-lock.json", "npm ci");
  before(web.instructions, "npm ci", "COPY --link reader/web/ ./");
  before(web.instructions, "COPY --link reader/web/ ./", "npm run build");
  assert.match(web.instructions.join("\n"), /RUN --mount=type=cache,target=\/root\/\.npm,sharing=locked\s+npm ci/);
  const final = stages("reader/Dockerfile").at(-1).instructions;
  before(final, "--from=web /web/dist /app/web", "reader/comicreader/");
});

for (const path of workflows) {
  test(`${path}: both images share cross-workflow v2 layer and package caches`, () => {
    const image = imageJob(path);
    assert.match(image, /cache-from: type=gha,version=2,scope=\$\{\{ matrix\.name \}\}/);
    assert.match(image, /cache-to: type=gha,version=2,mode=max,scope=\$\{\{ matrix\.name \}\}/);
    assert.match(image, /uses: actions\/cache@v4/);
    assert.match(image, /key: buildkit-mounts-v1-\$\{\{ runner\.os \}\}-\$\{\{ runner\.arch \}\}-\$\{\{ matrix\.name \}\}-\$\{\{ hashFiles\(matrix\.cache-inputs\) \}\}/);
    assert.match(image, /restore-keys: buildkit-mounts-v1-\$\{\{ runner\.os \}\}-\$\{\{ runner\.arch \}\}-\$\{\{ matrix\.name \}\}-/);
    assert.match(image, /uses: reproducible-containers\/buildkit-cache-dance@[0-9a-f]{40}\b/);
    assert.match(image, /skip-extraction: \$\{\{ steps\.packages\.outputs\.cache-hit == 'true' \}\}/);
    assert.ok(image.indexOf("uses: actions/cache@") < image.indexOf("uses: reproducible-containers/buildkit-cache-dance@"));
    assert.ok(image.indexOf("uses: reproducible-containers/buildkit-cache-dance@") < image.indexOf("uses: docker/build-push-action@"));
    assert.match(image, /platforms: linux\/amd64,linux\/arm64/);
  });
}

test("release and PR package-cache inputs hash the same files despite different checkout paths", () => {
  function inputs(path) {
    return [...imageJob(path).matchAll(/^          - name: (.+)\n            dockerfile: .+\n            cache-inputs: \|\n((?:              .+\n)+)/gm)].map(([, name, files]) => ({
      name,
      files: files.trim().split(/\n\s*/).map(file => file.replace(/^source\//, "")),
    }));
  }
  const main = inputs(workflows[0]);
  assert.deepEqual(main, [
    { name: "zcm-updater", files: ["Dockerfile", "requirements.txt"] },
    { name: "zcm-reader", files: ["reader/Dockerfile", "reader/requirements.txt", "reader/web/package-lock.json"] },
  ]);
  assert.deepEqual(inputs(workflows[1]), main);
  for (const image of main) for (const file of image.files) assert.ok(read(file).length > 0);
});

test("only current same-repository PR builds get shared-cache write access", () => {
  const workflow = read(workflows[1]);
  const image = imageJob(workflows[1]);
  assert.match(image, /if: needs\.current\.outputs\.build == 'true' && github\.event\.pull_request\.head\.repo\.full_name == github\.repository/);
  assert.match(image, /^    cache-mode: write$/m);
  assert.equal((workflow.match(/cache-mode:/g) ?? []).length, 1);
  assert.match(image, /outputs: type=image,name=\$\{\{ env\.IMAGE \}\},push-by-digest=true,name-canonical=true,push=true/);
  assert.match(image, /await publish\(/);
});

test("main pushes and cache-only benchmarks cannot log in or publish images", () => {
  const workflow = read(workflows[0]);
  assert.match(workflow, /push:\n    branches: \[main\]\n    tags: \["v\*"\]/);
  assert.match(workflow, /workflow_dispatch:\n    inputs:\n      cache-only:\n        description: .+\n        type: boolean\n        default: false/);
  const image = imageJob(workflows[0]);
  assert.match(image, /PUBLISH: \$\{\{ \(github\.event_name != 'push' \|\| startsWith\(github\.ref, 'refs\/tags\/'\)\) && !inputs\.cache-only \}\}/);
  assert.match(image, /uses: docker\/login-action@v3\n        if: env\.PUBLISH == 'true'/);
  assert.match(image, /push: \$\{\{ env\.PUBLISH == 'true' \}\}/);
  assert.match(workflow, /if \[ "\$\{\{ github\.event_name \}\}" != "schedule" \]; then/);
});
