const { execFileSync } = require("node:child_process");

const images = ["zcm-updater", "zcm-reader"];

function number(context) {
  const value = context.payload.pull_request.number;
  if (!Number.isSafeInteger(value) || value < 1) throw new Error("Expected a pull request number");
  return value;
}

async function current({ github, context, core }) {
  const { data: pull } = await github.rest.pulls.get({ ...context.repo, pull_number: number(context) });
  const ready = pull.state === "open" && pull.head.repo?.full_name === `${context.repo.owner}/${context.repo.repo}`
    && pull.head.sha === context.payload.pull_request.head.sha;
  if (!ready) core.info("The pull request is closed, from a fork, or has a newer commit; nothing to publish.");
  return ready;
}

async function publish({ github, context, core, image, digest, run = execFileSync }) {
  const owner = context.repo.owner.toLowerCase();
  if (!images.some(name => image === `ghcr.io/${owner}/${name}`) || !/^sha256:[0-9a-f]{64}$/.test(digest)) {
    throw new Error("Expected a reader or updater image and its sha256 digest");
  }
  // the build can finish after another commit or a close: only move the tag while this is still its head
  if (!await current({ github, context, core })) return;
  const tag = `${image}:pr-${number(context)}`;
  run("docker", ["buildx", "imagetools", "create", "--tag", tag, `${image}@${digest}`], { stdio: "inherit" });
  core.info(`Published ${tag} from ${context.payload.pull_request.head.sha}`);
}

async function cleanup({ github, context, core }) {
  const pullNumber = number(context);
  const { data: pull } = await github.rest.pulls.get({ ...context.repo, pull_number: pullNumber });
  if (pull.state !== "closed") {
    core.info("The pull request has reopened; keep its images.");
    return;
  }
  const tag = `pr-${pullNumber}`;
  const root = context.payload.repository.owner.type === "Organization" ? "/orgs" : "/users";
  const endpoint = `${root}/{owner}/packages/container/{package_name}/versions`;
  for (const image of images) {
    const params = { owner: context.repo.owner, package_name: image };
    let versions;
    try {
      // collect every page before deleting anything, or deletion moves entries between API pages
      versions = await github.paginate(`GET ${endpoint}`, { ...params, per_page: 100 });
    } catch (error) {
      if (error.status !== 404) throw error;
      core.info(`${image} has not been published; nothing to clean up.`);
      continue;
    }
    for (const version of versions) {
      const tags = version.metadata?.container?.tags ?? [];
      if (!tags.includes(tag)) continue;
      // GHCR deletes a whole version, not one tag: never take a release or another PR along with it
      if (tags.some(name => name !== tag)) {
        core.setFailed(`Refusing to delete ${image} version ${version.id}: it also carries ${tags.join(", ")}`);
        continue;
      }
      try {
        await github.request(`DELETE ${endpoint}/{package_version_id}`, { ...params, package_version_id: version.id });
      } catch (error) {
        if (error.status !== 404) throw error;
      }
      core.info(`Removed ${image}:${tag} (version ${version.id})`);
    }
  }
}

module.exports = { current, publish, cleanup };
