const assert = require("node:assert/strict");
const { test } = require("node:test");
const { current, publish, cleanup } = require("./pr-images.cjs");

const digest = `sha256:${"a".repeat(64)}`;
const image = "ghcr.io/zorntaov/comic-reader";

function fixture({ state = "open", sha = "head", repository = "ZornTaov/ZC-ComicUpdater", type = "User" } = {}) {
  const calls = [], failures = [], commands = [];
  const versions = { "comics-updater": [], "comic-reader": [] };
  const context = {
    repo: { owner: "ZornTaov", repo: "ZC-ComicUpdater" },
    payload: { repository: { owner: { type } }, pull_request: { number: 17, head: { sha: "head" } } },
  };
  const pull = { state, head: { sha, repo: repository === null ? null : { full_name: repository } } };
  const github = {
    rest: { pulls: { get: async params => {
      assert.deepEqual(params, { ...context.repo, pull_number: 17 });
      calls.push(["pull"]);
      return { data: pull };
    } } },
    paginate: async (route, params) => {
      calls.push(["list", route, params]);
      const found = versions[params.package_name];
      if (found instanceof Error) throw found;
      return found;
    },
    request: async (route, params) => { calls.push(["delete", route, params]); },
  };
  return { github, context, core: { info: () => {}, setFailed: text => failures.push(text) },
           image, digest, run: (...args) => commands.push(args), calls, failures, commands, versions, pull };
}

function version(id, tags) {
  return { id, metadata: { container: { tags } } };
}

function deleted(f) {
  return f.calls.filter(call => call[0] === "delete").map(call => [call[2].package_name, call[2].package_version_id]);
}

test("only a still-open PR at this exact same-repository head can publish", async () => {
  assert.equal(await current(fixture()), true);
  for (const options of [{ state: "closed" }, { sha: "newer-head" }, { repository: "Elsewhere/Fork" }, { repository: null }]) {
    const f = fixture(options);
    assert.equal(await current(f), false);
    await publish(f);
    assert.deepEqual(f.commands, []);
  }
});

test("the PR tag moves to the newly built digest without moving any release or nightly tag", async () => {
  const f = fixture();
  await publish(f);
  f.digest = `sha256:${"b".repeat(64)}`;
  await publish(f);
  assert.equal(f.commands.length, 2);
  for (const [command, args, options] of f.commands) {
    assert.equal(command, "docker");
    assert.deepEqual(args.slice(0, 5), ["buildx", "imagetools", "create", "--tag", `${image}:pr-17`]);
    assert.equal(options.stdio, "inherit");
  }
  assert.equal(f.commands[0][1][5], `${image}@${digest}`);
  assert.equal(f.commands[1][1][5], `${image}@${f.digest}`);
});

test("unexpected registry images, digests, and PR numbers are refused before any command", async () => {
  for (const changes of [{ image: "ghcr.io/elsewhere/other" }, { digest: "not-a-digest" }]) {
    const f = Object.assign(fixture(), changes);
    await assert.rejects(publish(f), /Expected a reader or updater image/);
    assert.deepEqual(f.commands, []);
  }
  const f = fixture();
  f.context.payload.pull_request.number = "17";
  await assert.rejects(publish(f), /Expected a pull request number/);
});

test("closing or merging removes only that PR tag from both images, including late API pages", async () => {
  const f = fixture({ state: "closed" });
  f.versions["comics-updater"] = [version(1, ["nightly", "sha-head"]), version(2, ["pr-17"]), version(3, ["pr-18"])];
  f.versions["comic-reader"] = [...Array.from({ length: 105 }, (_, n) => version(100 + n, [])),
                               version(250, ["pr-17"]), version(251, ["latest", "1.0.0"])];
  await cleanup(f);
  assert.deepEqual(deleted(f), [["comics-updater", 2], ["comic-reader", 250]]);
  assert.deepEqual(f.failures, []);
  const lists = f.calls.filter(call => call[0] === "list");
  assert.equal(lists.length, 2);
  assert.ok(lists.every(call => call[1] === "GET /users/{owner}/packages/container/{package_name}/versions"));
  assert.ok(lists.every(call => call[2].per_page === 100));
});

test("cleanup is safe to repeat when no matching tags remain", async () => {
  const f = fixture({ state: "closed" });
  f.versions["comics-updater"] = [version(1, ["pr-170"]), version(2, [])];
  await cleanup(f);
  await cleanup(f);
  assert.deepEqual(deleted(f), []);
  assert.deepEqual(f.failures, []);
});

test("a PR reopened while cleanup was queued keeps its images", async () => {
  const f = fixture();
  f.versions["comics-updater"] = [version(1, ["pr-17"])];
  await cleanup(f);
  assert.deepEqual(f.calls, [["pull"]]);
});

test("GHCR versions shared with another tag are never deleted", async () => {
  const f = fixture({ state: "closed" });
  f.versions["comics-updater"] = [version(1, ["pr-17", "latest"]), version(2, ["pr-17", "pr-18"])];
  f.versions["comic-reader"] = [version(3, ["pr-17"])];
  await cleanup(f);
  assert.deepEqual(deleted(f), [["comic-reader", 3]]);
  assert.equal(f.failures.length, 2);
  assert.ok(f.failures.every(text => text.startsWith("Refusing to delete")));
});

test("organization packages use the organization API route", async () => {
  const f = fixture({ state: "closed", type: "Organization" });
  f.versions["comics-updater"] = [version(1, ["pr-17"])];
  await cleanup(f);
  assert.equal(f.calls[1][1], "GET /orgs/{owner}/packages/container/{package_name}/versions");
  assert.equal(f.calls[2][1], "DELETE /orgs/{owner}/packages/container/{package_name}/versions/{package_version_id}");
});

test("a package or version already gone is harmless, but permission errors are not hidden", async () => {
  const f = fixture({ state: "closed" });
  f.versions["comics-updater"] = Object.assign(new Error("not found"), { status: 404 });
  f.versions["comic-reader"] = [version(1, ["pr-17"])];
  f.github.request = async () => { throw Object.assign(new Error("not found"), { status: 404 }); };
  await cleanup(f);
  f.versions["comics-updater"] = Object.assign(new Error("forbidden"), { status: 403 });
  await assert.rejects(cleanup(f), /forbidden/);
});
