import { BUILTIN_ASSET_URLS } from "../assets";
import {
  GOLDENDICT_BASE_CSS,
  GOLDENDICT_PRINT_CSS,
  getGoldenDictPresetCss,
} from "../styles/fidelity";
import { GOLDENDICT_RESPONSIVE_CSS } from "../styles/responsive";
import type {
  ArticleLayoutMode,
  GoldenDictTheme,
  LookupArticle,
  LookupResponse,
  ScriptPolicy,
} from "../types";
import { prepareArticleHtml } from "./article-html";
import { resolveResourceUrl } from "./link-router";
import { escapeStyleText, resolveThemeMode, themeToCss } from "./theme";

export interface ArticleDocumentOptions {
  apiBaseUrl: string;
  instanceId: string;
  scriptPolicy: ScriptPolicy;
  layoutMode?: ArticleLayoutMode;
  theme?: GoldenDictTheme;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function safeDomId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, (character) =>
    `_u${character.codePointAt(0)?.toString(16) ?? "0"}_`,
  );
}

function safeLanguageClass(value: string | undefined): string {
  return (value ?? "").toLowerCase().replace(/[^a-z0-9_-]/g, "-");
}

function articleIconUrl(article: LookupArticle, apiBaseUrl: string): string {
  if (!article.iconUrl) {
    return BUILTIN_ASSET_URLS["document.png"] ?? "";
  }
  return resolveResourceUrl(article.iconUrl, {
    apiBaseUrl,
    dictionaryId: article.dictionaryId,
    ...(article.resourceBaseUrl
      ? { resourceBaseUrl: article.resourceBaseUrl }
      : {}),
  });
}

function renderArticle(
  article: LookupArticle,
  apiBaseUrl: string,
  scriptPolicy: ScriptPolicy,
): string {
  const dictionaryId = escapeHtml(article.dictionaryId);
  const domId = safeDomId(article.dictionaryId);
  const body = prepareArticleHtml(article, apiBaseUrl, scriptPolicy);
  const sourceLanguage = safeLanguageClass(article.sourceLanguage);
  const targetLanguage = escapeHtml(article.targetLanguage ?? "");
  const iconUrl = escapeHtml(articleIconUrl(article, apiBaseUrl));
  return `
    <article class="gdarticle" id="gdfrom-${domId}" data-gd-id="${dictionaryId}">
      <gd-dict-header class="gddictname" id="gddictname-${domId}"
        role="button" tabindex="0" aria-expanded="true" aria-controls="gd-${domId}">
        <span class="gddicticon"><img src="${iconUrl}" alt=""></span>
        <span class="gdfromprefix">From </span>
        <span class="gddicttitle">${escapeHtml(article.dictionaryName)}</span>
        <span class="collapse_expand_area" aria-hidden="true">
          <img class="gdcollapseicon" id="expandicon-${domId}" alt="">
        </span>
      </gd-dict-header>
      <section class="gdarticlebody gdlangfrom-${sourceLanguage}"
        lang="${targetLanguage}" style="display:block" id="gd-${domId}">${body}</section>
    </article>
    <div style="clear:both;" aria-hidden="true"></div>
    <span class="gdarticleseparator"></span>`;
}

function renderSuggestions(suggestions: readonly string[]): string {
  if (!suggestions.length) {
    return "";
  }
  const links = suggestions
    .map(
      (suggestion) =>
        `<a href="#" data-gd-action="lookup" data-gd-word="${escapeHtml(suggestion)}">${escapeHtml(suggestion)}</a>`,
    )
    .join(", ");
  return `<div class="gdstemmedsuggestion">
    <span class="gdstemmedsuggestion_head">Close words: </span>
    <span class="gdstemmedsuggestion_body">${links}</span>
  </div>`;
}

function bridgeScript(
  instanceId: string,
  themeMode: "light" | "dark",
): string {
  const config = JSON.stringify({
    namespace: "goldendict-web",
    instanceId,
    themeMode,
    expandOptIcon: BUILTIN_ASSET_URLS["expand_opt.svg"],
    collapseOptIcon: BUILTIN_ASSET_URLS["collapse_opt.svg"],
  }).replace(/<\//g, "<\\/");
  return `(function(){
    "use strict";
    const config=${config};
    const post=(type,detail={})=>parent.postMessage({
      namespace:config.namespace,
      instanceId:config.instanceId,
      type,
      detail
    },"*");
    const reportResourceError=(failure)=>{
      if(!failure||typeof failure.url!=="string"||!failure.url)return;
      if(failure.resourceType!=="stylesheet"&&failure.resourceType!=="script")return;
      post("resource-error",{
        resourceType:failure.resourceType,
        url:failure.url,
        dictionaryId:typeof failure.dictionaryId==="string"&&failure.dictionaryId
          ?failure.dictionaryId
          :undefined
      });
    };
    globalThis.__GOLDENDICT_WEB_REPORT_RESOURCE_ERROR__=reportResourceError;
    const pendingResourceErrors=globalThis.__GOLDENDICT_WEB_RESOURCE_ERRORS__;
    if(Array.isArray(pendingResourceErrors)){
      pendingResourceErrors.splice(0).forEach(reportResourceError);
    }
    const verifyStylesheets=()=>{
      document.querySelectorAll('link[rel~="stylesheet"][href]').forEach((link)=>{
        if(!(link instanceof HTMLLinkElement)||link.disabled||link.sheet!==null)return;
        reportResourceError({
          resourceType:"stylesheet",
          url:link.href,
          dictionaryId:link.closest(".gdarticle")?.getAttribute("data-gd-id")||undefined
        });
      });
    };
    const articleOf=(target)=>target instanceof Element?target.closest(".gdarticle"):null;
    const articleId=(article)=>article?.getAttribute("data-gd-id")||"";
    const syncDictionaryTheme=()=>{
      if(document.documentElement.getAttribute("data-gd-theme")!==config.themeMode){
        document.documentElement.setAttribute("data-gd-theme",config.themeMode);
      }
      if(document.documentElement.getAttribute("data-darkreader-scheme")!==config.themeMode){
        document.documentElement.setAttribute("data-darkreader-scheme",config.themeMode);
      }
      document.querySelectorAll(".oaldpe").forEach((container)=>{
        if(container.getAttribute("data-theme")!==config.themeMode){
          container.setAttribute("data-theme",config.themeMode);
        }
      });
    };
    const themeObserver=new MutationObserver(syncDictionaryTheme);
    themeObserver.observe(document.documentElement,{
      subtree:true,
      childList:true,
      attributes:true,
      attributeFilter:["data-theme","data-darkreader-scheme"]
    });
    syncDictionaryTheme();
    const setActive=(article,notify=true)=>{
      if(!article)return;
      document.querySelector(".gdactivearticle")?.classList.remove("gdactivearticle");
      article.classList.add("gdactivearticle");
      if(notify)post("active-article",{dictionaryId:articleId(article)});
    };
    const toggleArticle=(article)=>{
      if(!article)return;
      const body=article.querySelector(".gdarticlebody");
      const header=article.querySelector(".gddictname");
      const icon=article.querySelector(".gdexpandicon,.gdcollapseicon");
      if(!body||!header)return;
      const collapsed=!body.hidden&&getComputedStyle(body).display!=="none";
      body.hidden=collapsed;
      body.style.display=collapsed?"none":"block";
      article.classList.toggle("gdcollapsedarticle",collapsed);
      header.setAttribute("aria-expanded",String(!collapsed));
      if(icon)icon.className=collapsed?"gdexpandicon":"gdcollapseicon";
      post("article-toggle",{dictionaryId:articleId(article),collapsed});
      requestSize();
    };
    const expandOptional=(expanderId,optionalId)=>{
      const expander=document.getElementById(expanderId);
      const optional=document.getElementById(optionalId);
      if(!expander||!optional)return;
      const expanding=expander.getAttribute("aria-expanded")!=="true"&&expander.getAttribute("alt")!=="[-]";
      expander.setAttribute("aria-expanded",String(expanding));
      expander.setAttribute("alt",expanding?"[-]":"[+]");
      if(expander instanceof HTMLImageElement)expander.src=expanding?config.collapseOptIcon:config.expandOptIcon;
      optional.querySelectorAll(".dsl_opt").forEach((part)=>{
        part.style.display=expanding?"inline":"none";
      });
      requestSize();
    };
    globalThis.gdExpandOptPart=expandOptional;
    globalThis.gdMakeArticleActive=(id,noEvent)=>{
      const article=[...document.querySelectorAll(".gdarticle")].find((item)=>articleId(item)===id);
      setActive(article,!noEvent);
    };
    globalThis.gdCheckArticlesNumber=()=>{
      const articles=document.querySelectorAll(".gdarticle");
      if(articles.length===1&&articles[0].classList.contains("gdcollapsedarticle"))toggleArticle(articles[0]);
    };
    globalThis.articleview={
      onJsActiveArticleChanged:(id)=>post("active-article",{dictionaryId:String(id).replace(/^gdfrom-/,"")}),
      linkClickedInHtml:()=>{},
      collapseInHtml:(id,collapsed)=>post("article-toggle",{dictionaryId:id,collapsed:Boolean(collapsed)})
    };
    const handleAction=(anchor,event)=>{
      const action=anchor.getAttribute("data-gd-action");
      if(!action)return false;
      event.preventDefault();
      if(action==="lookup"){
        const dictionaries=(anchor.getAttribute("data-gd-dictionaries")||"").split(",").filter(Boolean);
        post("lookup",{
          word:anchor.getAttribute("data-gd-word")||anchor.textContent||"",
          anchor:anchor.getAttribute("data-gd-anchor")||undefined,
          dictionaryIds:dictionaries.length?dictionaries:undefined
        });
      }else if(action==="external"){
        post("external-link",{url:anchor.href});
      }else if(action==="audio"||action==="video"||action==="resource"){
        post("media",{kind:action,url:anchor.href,dictionaryId:anchor.getAttribute("data-gd-dictionary")||undefined});
      }
      return true;
    };
    document.addEventListener("click",(event)=>{
      const target=event.target;
      if(!(target instanceof Element))return;
      const optional=target.closest(".hidden_expand_opt[data-gd-optional]");
      if(optional){
        event.preventDefault();
        expandOptional(optional.getAttribute("data-gd-expander")||optional.id,optional.getAttribute("data-gd-optional"));
        return;
      }
      const anchor=target.closest("a,area");
      if(anchor&&handleAction(anchor,event))return;
      const header=target.closest(".gddictname");
      const article=articleOf(target);
      if(header){event.preventDefault();toggleArticle(article);event.stopPropagation();}
      setActive(article,true);
    });
    document.addEventListener("contextmenu",(event)=>setActive(articleOf(event.target),true));
    document.addEventListener("keydown",(event)=>{
      if(event.key!=="Enter"&&event.key!==" ")return;
      const target=event.target;
      if(!(target instanceof Element))return;
      const header=target.closest(".gddictname");
      if(header){event.preventDefault();toggleArticle(articleOf(header));}
    });
    let resizeFrame=0;
    let lastHeight=0;
    const requestSize=()=>{
      cancelAnimationFrame(resizeFrame);
      resizeFrame=requestAnimationFrame(()=>{
        resizeFrame=0;
        const height=Math.ceil(Math.max(
          document.body.scrollHeight,
          document.body.offsetHeight,
          document.body.getBoundingClientRect().height
        ));
        if(height===lastHeight)return;
        lastHeight=height;
        post("height",{height});
      });
    };
    addEventListener("message",(event)=>{
      const message=event.data;
      if(event.source!==parent||message?.namespace!==config.namespace||message?.instanceId!==config.instanceId)return;
      if(message.type==="scroll-anchor")document.getElementById(message.anchor)?.scrollIntoView({block:"start"});
      if(message.type==="scroll-article"){
        const article=[...document.querySelectorAll(".gdarticle")].find((item)=>articleId(item)===message.dictionaryId);
        article?.scrollIntoView({block:"start"});setActive(article,false);
      }
    });
    const resizeObserver=new ResizeObserver(requestSize);
    resizeObserver.observe(document.body);
    addEventListener("resize",requestSize,{passive:true});
    addEventListener("load",()=>{verifyStylesheets();requestSize();post("ready",{});});
  })();`;
}

function contentSecurityPolicy(
  scriptPolicy: ScriptPolicy,
  nonce: string,
): string {
  const scriptSource =
    scriptPolicy === "none"
      ? `'nonce-${nonce}'`
      : "'unsafe-inline' 'unsafe-eval' data: blob: http: https:";
  const connectSource = scriptPolicy === "none" ? "'none'" : "http: https:";
  return [
    "default-src 'none'",
    "img-src data: blob: http: https:",
    "media-src data: blob: http: https:",
    "font-src data: blob: http: https:",
    "style-src 'unsafe-inline' data: blob: http: https:",
    `script-src ${scriptSource}`,
    `connect-src ${connectSource}`,
    "frame-src http: https:",
    "object-src 'none'",
    "form-action 'none'",
    "base-uri 'none'",
  ].join("; ");
}

function compatibilityBootstrapScript(): string {
  // GoldenDict-ng injects this object at DocumentCreation in ArticleWebView.
  // Keep it ahead of dictionary markup so sidecars observe the same host name
  // while retaining the browser package's opaque-origin sandbox boundary. The
  // capture listener must also precede dictionary markup: resource error events
  // do not bubble and a failed sidecar can otherwise leave an unstyled article
  // looking like a successful render.
  return `(function(){
    globalThis.__DICT__={name:"GoldenDict",version:"web"};
    const pending=[];
    globalThis.__GOLDENDICT_WEB_RESOURCE_ERRORS__=pending;
    addEventListener("error",(event)=>{
      const target=event.target;
      let resourceType="";
      let url="";
      if(target instanceof HTMLLinkElement&&target.relList.contains("stylesheet")){
        resourceType="stylesheet";
        url=target.href;
      }else if(target instanceof HTMLScriptElement&&target.src){
        resourceType="script";
        url=target.src;
      }
      if(!resourceType||!url)return;
      const article=target.closest(".gdarticle");
      const failure={
        resourceType,
        url,
        dictionaryId:article?.getAttribute("data-gd-id")||undefined
      };
      const report=globalThis.__GOLDENDICT_WEB_REPORT_RESOURCE_ERROR__;
      if(typeof report==="function")report(failure);
      else pending.push(failure);
    },true);
  })();`;
}

export function buildArticleDocument(
  response: LookupResponse,
  options: ArticleDocumentOptions,
): string {
  const theme = options.theme ?? {};
  const themeMode = resolveThemeMode(theme.mode);
  const layoutMode = options.layoutMode ?? "fidelity";
  const nonce = options.instanceId.replace(/[^a-zA-Z0-9_-]/g, "");
  const articles = response.articles
    .map((article) =>
      renderArticle(article, options.apiBaseUrl, options.scriptPolicy),
    )
    .join("");
  const content = articles
    ? `${articles}<div class="empty-space" aria-hidden="true"></div>`
    : `<div class="gdnotfound"><p>No translation for <b>${escapeHtml(response.word)}</b> was found.</p></div>`;
  const title = theme.brandName
    ? `${response.word} — ${theme.brandName}`
    : response.word;
  return `<!doctype html>
<html data-gd-theme="${themeMode}" data-gd-layout="${layoutMode}" data-darkreader-scheme="${themeMode}"><head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="${escapeHtml(contentSecurityPolicy(options.scriptPolicy, nonce))}">
  <title>${escapeHtml(title)}</title>
  <script nonce="${nonce}" data-gd-runtime="compatibility">${compatibilityBootstrapScript()}</script>
  <style>${escapeStyleText(GOLDENDICT_BASE_CSS)}</style>
  <style>${escapeStyleText(getGoldenDictPresetCss(theme.preset))}</style>
  ${layoutMode === "responsive" ? `<style data-gd-style="responsive">${escapeStyleText(GOLDENDICT_RESPONSIVE_CSS)}</style>` : ""}
  <style>${themeToCss(theme)}</style>
  <style media="print">${escapeStyleText(GOLDENDICT_PRINT_CSS)}</style>
</head><body>
  ${content}
  ${renderSuggestions(response.suggestions)}
  <script nonce="${nonce}">${bridgeScript(options.instanceId, themeMode).replace(/<\/script/gi, "<\\/script")}</script>
</body></html>`;
}
