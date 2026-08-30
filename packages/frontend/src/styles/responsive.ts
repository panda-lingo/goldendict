/**
 * Browser-only layout safeguards layered after GoldenDict-ng's pinned styles.
 * Keeping these rules separate means upstream stylesheet syncs remain exact.
 */
export const GOLDENDICT_RESPONSIVE_CSS = `
  :root {
    --gd-responsive-gutter: clamp(0.5rem, 2.5vw, 1rem);
  }

  html,
  body {
    box-sizing: border-box;
    inline-size: 100%;
    min-inline-size: 0;
    max-inline-size: 100%;
  }

  *,
  *::before,
  *::after {
    box-sizing: inherit;
  }

  body {
    margin: 0;
    padding: var(--gd-responsive-gutter);
    overflow-wrap: break-word;
  }

  .gdarticle,
  .gdarticlebody,
  .gdstemmedsuggestion {
    min-inline-size: 0;
    max-inline-size: 100%;
  }

  .gddictname {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    max-inline-size: 100%;
  }

  .gddicticon,
  .collapse_expand_area {
    flex: 0 0 auto;
  }

  .gddicttitle {
    flex: 1 1 auto;
    min-inline-size: 0;
    overflow-wrap: anywhere;
  }

  .collapse_expand_area {
    margin-inline-start: auto;
  }

  .gddictname:focus-visible {
    outline: 2px solid var(--link-color, currentColor);
    outline-offset: -2px;
  }

  /* Keep nested, absolutely positioned sidecar controls at their authored size. */
  .gdarticlebody > :where(div, section, article, aside, header, footer, figure),
  .gdarticlebody :where(img, picture, video, canvas, svg, iframe, object, embed),
  .gdarticlebody :where(pre, table) {
    max-inline-size: 100% !important;
  }

  .gdarticlebody :where(img, video, canvas, svg) {
    block-size: auto !important;
  }

  .gdarticlebody :where(a, p, li, dd, dt, td, th, code) {
    overflow-wrap: anywhere;
  }

  .gdarticlebody pre {
    overflow-x: auto !important;
    overscroll-behavior-inline: contain;
    -webkit-overflow-scrolling: touch;
  }

  .gdstemmedsuggestion_body {
    inline-size: auto;
    margin-inline: 0.75rem;
  }

  .empty-space {
    block-size: clamp(6rem, 20vw, 15rem);
  }

  @media (max-width: 64rem) {
    .gdarticlebody table {
      display: block !important;
      overflow-x: auto !important;
      overscroll-behavior-inline: contain;
      -webkit-overflow-scrolling: touch;
    }
  }

  @media (max-width: 40rem) {
    :root {
      --gd-responsive-gutter: 0.5rem;
    }

    .gddictname {
      min-block-size: 2.75rem;
      margin-block: 0.35rem;
    }

    .gdarticlebody :where(.infobox, .navbox, .thumb, .tright, .tleft) {
      float: none !important;
      inline-size: auto !important;
      max-inline-size: 100% !important;
      margin-inline: 0 !important;
    }

    .gdarticlebody .thumbinner {
      inline-size: 100% !important;
      max-inline-size: 100% !important;
    }
  }

  @media (pointer: coarse) {
    .gddictname {
      min-block-size: 2.75rem;
    }
  }
`;
