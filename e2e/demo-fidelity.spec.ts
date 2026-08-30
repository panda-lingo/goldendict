import {
  chromium,
  expect,
  test,
  type FrameLocator,
  type Page,
} from "@playwright/test";

const resourceNames = [
  "fidelity.css",
  "fixture-jquery.js",
  "fixture-sidecar.js",
] as const;
const GOLDENDICT_RESOURCE_ERROR_EVENT = "goldendict-resource-error";

interface RenderedLookup {
  bridgeId: string;
  frame: FrameLocator;
  iframeHeight: number;
}

async function lookup(page: Page, word: string): Promise<RenderedLookup> {
  await page.locator("#query").fill(word);
  await page.getByRole("button", { name: "Look up" }).click();

  const view = page.locator("#dictionary-view");
  await expect.poll(() => view.evaluate((node) => {
    const response = (node as HTMLElement & { response?: { word?: string } }).response;
    return response?.word;
  })).toBe(word);
  await expect(page.locator("#view-state")).toHaveAttribute("data-state", "ready");

  const iframe = view.locator("iframe");
  await expect(iframe).toBeVisible();
  const frame = iframe.contentFrame();
  const fixture = frame.locator(".fixture-snapshot");
  await expect(fixture).toHaveAttribute("data-ready", "true");
  await expect(fixture.locator(".oald.visible")).toBeVisible();

  const srcdoc = (await iframe.getAttribute("srcdoc")) ?? "";
  const bridgeId = /"instanceId":"([^"]+)"/.exec(srcdoc)?.[1] ?? "";
  expect(bridgeId).not.toBe("");
  return {
    bridgeId,
    frame,
    iframeHeight: await iframe.evaluate((element) => element.getBoundingClientRect().height),
  };
}

async function geometryAtDeviceScaleFactor(deviceScaleFactor: number) {
  const scaledBrowser = await chromium.launch({
    args: [`--force-device-scale-factor=${deviceScaleFactor}`],
    channel: "chromium",
    headless: true,
  });
  const context = await scaledBrowser.newContext({
    colorScheme: "light",
    deviceScaleFactor,
    locale: "en-US",
    timezoneId: "UTC",
    viewport: { width: 2048, height: 1228 },
  });
  try {
    const page = await context.newPage();
    await page.goto("http://127.0.0.1:4173/");
    await expect(page.locator("#connection-text")).toHaveText("1 dictionary ready");
    const rendered = await lookup(page, "example");
    return await rendered.frame.locator("html").evaluate(() => {
      const rect = (selector: string) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element) {
          throw new Error(`Missing geometry fixture ${selector}`);
        }
        const bounds = element.getBoundingClientRect();
        return {
          height: bounds.height,
          width: bounds.width,
          x: bounds.x,
          y: bounds.y,
        };
      };
      const fixture = document.querySelector<HTMLElement>(".fixture-snapshot");
      if (!fixture) {
        throw new Error("Missing synthetic fixture");
      }
      return {
        devicePixelRatio,
        dictionaryName: (globalThis as typeof globalThis & {
          __goldendictFixtureAtLoad?: { dictionaryName?: string };
        }).__goldendictFixtureAtLoad?.dictionaryName,
        fixtureFontSize: getComputedStyle(fixture).fontSize,
        fixtureLineHeight: getComputedStyle(fixture).lineHeight,
        gear: rect(".oaldpe-config-gear__icon"),
        metricBox: rect(".fixture-metric-box"),
        webtop: rect(".webtop"),
      };
    });
  } finally {
    await context.close();
    await scaledBrowser.close();
  }
}

test("preserves authored fidelity and initializes sidecars on consecutive lookups", async ({
  page,
}) => {
  const browserErrors: string[] = [];
  const failedResources: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      browserErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("requestfailed", (request) => {
    if (request.url().includes("/api/v1/")) {
      failedResources.push(`${request.url()}: ${request.failure()?.errorText ?? "failed"}`);
    }
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/v1/") && response.status() >= 400) {
      failedResources.push(`${response.url()}: HTTP ${response.status()}`);
    }
  });

  await page.goto("/");
  await expect(page.locator("#connection-text")).toHaveText("1 dictionary ready");
  await page.evaluate(async () => {
    await fetch("/__fixture/reset");
  });
  await expect(page.locator("#script-policy")).toHaveValue("sandboxed");
  await expect(page.locator("#layout-mode")).toHaveValue("fidelity");

  const view = page.locator("#dictionary-view");
  const iframe = view.locator("iframe");
  await expect(iframe).toHaveAttribute("sandbox", "allow-scripts");

  const first = await lookup(page, "example");
  await expect(first.frame.locator("html")).toHaveAttribute("data-gd-layout", "fidelity");
  await expect(first.frame.locator('style[data-gd-style="responsive"]')).toHaveCount(0);
  await expect(first.frame.locator(".headword")).toHaveText("example");
  // Font rasterization varies with the host font packages. Keep the visual
  // baseline focused on authored layout/background geometry; typography and
  // colors are asserted from computed styles immediately below.
  await first.frame.locator("head").evaluate((head) => {
    const style = document.createElement("style");
    style.dataset.fixtureScreenshot = "true";
    style.textContent =
      ".fixture-snapshot,.fixture-snapshot *{color:transparent!important;text-shadow:none!important}" +
      ".fixture-snapshot *::before,.fixture-snapshot *::after,.fixture-snapshot *::first-letter{color:transparent!important}" +
      ".fixture-definition{opacity:0!important}";
    head.append(style);
  });
  try {
    await expect(first.frame.locator(".fixture-snapshot")).toHaveScreenshot(
      "synthetic-fidelity.png",
    );
  } finally {
    await first.frame
      .locator('style[data-fixture-screenshot="true"]')
      .evaluate((style) => style.remove());
  }

  const runtimeAtLoad = await first.frame.locator("html").evaluate(() => {
    const runtime = globalThis as typeof globalThis & {
      __goldendictFixtureAtLoad?: {
        dictionaryName: string | null;
        userAgent: string;
      };
    };
    return runtime.__goldendictFixtureAtLoad;
  });
  expect(runtimeAtLoad).toEqual({
    dictionaryName: "GoldenDict",
    userAgent: expect.not.stringMatching(/goldendict/i),
  });

  const firstMetrics = await first.frame.locator("html").evaluate(() => {
    const fixture = document.querySelector<HTMLElement>(".fixture-snapshot");
    const webtop = document.querySelector<HTMLElement>(".webtop");
    const gear = document.querySelector<HTMLElement>(".oaldpe-config-gear__icon");
    const metricBox = document.querySelector<HTMLElement>(".fixture-metric-box");
    const headword = document.querySelector<HTMLElement>(".fixture-headword");
    const activeNav = document.querySelector<HTMLElement>(".fixture-nav .active");
    if (!fixture || !webtop || !gear || !metricBox || !headword || !activeNav) {
      throw new Error("Synthetic fidelity fixture did not initialize");
    }
    const webtopRect = webtop.getBoundingClientRect();
    const gearRect = gear.getBoundingClientRect();
    const metricBoxRect = metricBox.getBoundingClientRect();
    const fixtureStyle = getComputedStyle(fixture);
    return {
      bodyMargin: getComputedStyle(document.body).margin,
      boxSizing: getComputedStyle(metricBox).boxSizing,
      documentClientWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      fixtureFontSize: fixtureStyle.fontSize,
      fixtureLineHeight: fixtureStyle.lineHeight,
      fixtureColor: fixtureStyle.color,
      headwordColor: getComputedStyle(headword).color,
      activeNavBackground: getComputedStyle(activeNav).backgroundColor,
      gear: {
        bottom: gearRect.bottom,
        height: gearRect.height,
        left: gearRect.left,
        right: gearRect.right,
        top: gearRect.top,
        width: gearRect.width,
      },
      metricBoxWidth: metricBoxRect.width,
      sidecarExecutions: fixture.dataset.sidecarExecutions,
      webtop: {
        bottom: webtopRect.bottom,
        left: webtopRect.left,
        right: webtopRect.right,
        top: webtopRect.top,
      },
    };
  });
  expect(firstMetrics.bodyMargin).toBe("8px");
  expect(firstMetrics.boxSizing).toBe("content-box");
  expect(firstMetrics.fixtureFontSize).toBe("15px");
  expect(firstMetrics.fixtureLineHeight).toBe("21px");
  expect(firstMetrics.fixtureColor).toBe("rgb(51, 51, 51)");
  expect(firstMetrics.headwordColor).toBe("rgb(6, 114, 206)");
  expect(firstMetrics.activeNavBackground).toBe("rgb(75, 139, 69)");
  expect(firstMetrics.metricBoxWidth).toBe(282);
  expect(firstMetrics.gear.width).toBe(30);
  expect(firstMetrics.gear.height).toBe(30);
  expect(firstMetrics.gear.left).toBeGreaterThan(firstMetrics.webtop.left);
  expect(firstMetrics.gear.right).toBeLessThan(firstMetrics.webtop.right);
  expect(firstMetrics.gear.top).toBeGreaterThan(firstMetrics.webtop.top);
  expect(firstMetrics.gear.bottom).toBeLessThan(firstMetrics.webtop.bottom);
  expect(firstMetrics.documentScrollWidth).toBeLessThanOrEqual(
    firstMetrics.documentClientWidth,
  );
  expect(firstMetrics.sidecarExecutions).toBe("1");
  expect(first.iframeHeight).toBeGreaterThan(500);

  const firstResourceStats = await page.evaluate(async () => {
    const response = await fetch("/__fixture/stats");
    return await response.json() as Record<string, number>;
  });
  for (const resourceName of resourceNames) {
    expect(firstResourceStats[resourceName]).toBe(1);
  }

  const second = await lookup(page, "hello");
  expect(second.bridgeId).not.toBe(first.bridgeId);
  await expect(second.frame.locator(".headword")).toHaveText("hello");
  await expect(second.frame.locator(".fixture-snapshot")).toHaveAttribute(
    "data-runtime",
    "goldendict",
  );
  await expect(second.frame.locator(".fixture-snapshot")).toHaveAttribute(
    "data-sidecar-executions",
    "1",
  );
  await expect(second.frame.locator(".fixture-definition")).toContainText("greeting");
  await expect(second.frame.locator(".fixture-snapshot")).not.toContainText(
    "authored dictionary layout",
  );
  expect(second.iframeHeight).toBeGreaterThan(500);

  const secondResourceStats = await page.evaluate(async () => {
    const response = await fetch("/__fixture/stats");
    return await response.json() as Record<string, number>;
  });
  for (const resourceName of resourceNames) {
    expect(secondResourceStats[resourceName]).toBeGreaterThanOrEqual(1);
    expect(secondResourceStats[resourceName]).toBeLessThanOrEqual(2);
  }
  expect(failedResources).toEqual([]);
  expect(browserErrors).toEqual([]);
});

for (const blocked of [
  { name: "fidelity.css", resourceType: "stylesheet" },
  { name: "fixture-sidecar.js", resourceType: "script" },
] as const) {
  test(`reports a blocked dictionary ${blocked.resourceType} instead of ready`, async ({
    page,
  }) => {
    const failureWord = `blocked-${blocked.resourceType}`;
    if (blocked.resourceType === "script") {
      await page.route(
        (url) =>
          url.pathname.endsWith(`/${blocked.name}`) &&
          url.searchParams.get("lookup") === failureWord,
        (route) => route.abort("connectionrefused"),
      );
    }
    await page.goto("/");
    await expect(page.locator("#connection-text")).toHaveText("1 dictionary ready");

    await page.locator("#query").fill(failureWord);
    await page.getByRole("button", { name: "Look up" }).click();

    const state = page.locator("#view-state");
    const view = page.locator("#dictionary-view");
    if (blocked.resourceType === "stylesheet") {
      // Chromium may treat failed stylesheet responses as an empty loaded
      // sheet. Dispatch the browser's element error deterministically here;
      // unit coverage separately proves the generated capture listener.
      const frame = view.locator("iframe").contentFrame();
      const stylesheet = frame.locator(`link[href*="${blocked.name}"]`);
      await expect(stylesheet).toHaveCount(1);
      await stylesheet.evaluate((element) => element.dispatchEvent(new Event("error")));
    }
    await expect(state).toHaveAttribute("data-state", "error");
    await expect(view.locator("iframe")).toBeVisible();
    await expect(view.locator('[part="status"]')).toContainText(blocked.name);
    await expect(page.locator("#event-log")).toContainText(
      GOLDENDICT_RESOURCE_ERROR_EVENT,
    );

    const diagnostics = await view.evaluate((node) => {
      const component = node as HTMLElement & {
        state: string;
        error?: Error;
        resourceErrors: Array<{
          resourceType: string;
          url: string;
          dictionaryId?: string;
        }>;
      };
      return {
        state: component.state,
        error: component.error?.message,
        resourceErrors: component.resourceErrors,
      };
    });
    expect(diagnostics.state).toBe("error");
    expect(diagnostics.error).toContain(blocked.name);
    expect(diagnostics.resourceErrors).toEqual([
      expect.objectContaining({
        dictionaryId: "synthetic-fidelity",
        resourceType: blocked.resourceType,
        url: expect.stringContaining(blocked.name),
      }),
    ]);
  });
}

test("keeps logical article geometry invariant across device scale factors", async () => {
  const dprOne = await geometryAtDeviceScaleFactor(1);
  const dprOneAndHalf = await geometryAtDeviceScaleFactor(1.5);

  expect(dprOne.devicePixelRatio).toBe(1);
  expect(dprOneAndHalf.devicePixelRatio).toBe(1.5);
  expect(dprOne.dictionaryName).toBe("GoldenDict");
  expect(dprOneAndHalf.dictionaryName).toBe("GoldenDict");
  expect(dprOne.fixtureFontSize).toBe("15px");
  expect(dprOne.fixtureLineHeight).toBe("21px");
  expect(dprOneAndHalf.fixtureFontSize).toBe(dprOne.fixtureFontSize);
  expect(dprOneAndHalf.fixtureLineHeight).toBe(dprOne.fixtureLineHeight);

  for (const selector of ["gear", "metricBox", "webtop"] as const) {
    for (const dimension of ["height", "width", "x", "y"] as const) {
      expect(
        Math.abs(
          dprOneAndHalf[selector][dimension] - dprOne[selector][dimension],
        ),
        `${selector}.${dimension} changed in CSS pixels at DPR 1.5`,
      ).toBeLessThanOrEqual(
        2,
      );
    }
  }
});
