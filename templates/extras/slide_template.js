/**
 * slide_template.js — プレゼンテーション用デザインシステム
 *
 * 使い方:
 *   const { createPresentation, C, addFooter, addContentSlide,
 *           addSectionTitle, addSubtitle, makeShadow, makeCardShadow,
 *           iconToBase64Png } = require("./slide_template");
 *
 *   const pres = createPresentation("タイトル", "著者名");
 *   const slide = pres.addSlide();
 *   addContentSlide(slide);
 *   addSectionTitle(slide, "見出し");
 *   ...
 *   pres.writeFile({ fileName: "output.pptx" });
 */

const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");

// ============================================================
// Color Palette — 内容に合わせてこのブロックだけ差し替えてOK
// ============================================================
const C = {
  navy:       "1A3C5E",
  blue:       "2E86AB",
  teal:       "0D9488",
  orange:     "F18F01",
  lightBg:    "F0F4F8",
  white:      "FFFFFF",
  darkText:   "1E293B",
  bodyText:   "334155",
  muted:      "64748B",
  lightLine:  "CBD5E1",
  tableHead:  "1A3C5E",
  tableAlt:   "F0F4F8",
  accent2:    "14B8A6",
};

// ============================================================
// Shadow Factories — 毎回新規オブジェクトを返す（pptxgenjs の仕様）
// ============================================================
const makeShadow = () => ({
  type: "outer", blur: 4, offset: 2, angle: 135,
  color: "000000", opacity: 0.10
});
const makeCardShadow = () => ({
  type: "outer", blur: 6, offset: 2, angle: 135,
  color: "000000", opacity: 0.12
});

// ============================================================
// Icon Helpers
// ============================================================
function renderIconSvg(IconComponent, color = "#000000", size = 256) {
  return ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComponent, { color, size: String(size) })
  );
}

async function iconToBase64Png(IconComponent, color, size = 256) {
  const svg = renderIconSvg(IconComponent, color, size);
  const pngBuffer = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + pngBuffer.toString("base64");
}

// ============================================================
// Presentation Factory
// ============================================================
function createPresentation(title, author) {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.title = title || "Presentation";
  pres.author = author || "";
  return pres;
}

// ============================================================
// Slide Helpers
// ============================================================

/** コンテンツスライド共通の背景 + 上部アクセントバー */
function addContentSlide(slide) {
  slide.background = { color: C.lightBg };
  slide.addShape("rect", {
    x: 0, y: 0, w: 10, h: 0.06,
    fill: { color: C.blue }
  });
}

/** スライドタイトル（26pt、navy） */
function addSectionTitle(slide, text) {
  slide.addText(text, {
    x: 0.6, y: 0.35, w: 8.8, h: 0.55,
    fontSize: 26, fontFace: "Trebuchet MS",
    color: C.navy, bold: true, margin: 0
  });
}

/** サブタイトル（13pt、muted） */
function addSubtitle(slide, text) {
  slide.addText(text, {
    x: 0.6, y: 0.95, w: 8.8, h: 0.35,
    fontSize: 13, fontFace: "Calibri",
    color: C.muted, margin: 0
  });
}

/** フッター（ページ番号 + デッキ名） */
function addFooter(slide, slideNum, totalSlides, deckName, isDark = false) {
  const footerColor = isDark ? "8899AA" : C.muted;
  slide.addText(`${slideNum} / ${totalSlides}`, {
    x: 8.8, y: 5.2, w: 1, h: 0.3,
    fontSize: 9, color: footerColor,
    align: "right", fontFace: "Calibri"
  });
  slide.addText(deckName || "", {
    x: 0.5, y: 5.2, w: 3, h: 0.3,
    fontSize: 9, color: footerColor,
    align: "left", fontFace: "Calibri"
  });
}

/**
 * セクション区切りスライド（ダーク背景）
 * @param {Object} pres - pptxgenjs instance
 * @param {string} sectionNum - "01", "02", ...
 * @param {string} title - セクションタイトル
 * @param {string} subtitle - サブタイトル
 */
function addSectionDivider(pres, sectionNum, title, subtitle) {
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape("rect", {
    x: 0, y: 0, w: 10, h: 0.08,
    fill: { color: C.orange }
  });
  s.addText(`SECTION ${sectionNum}`, {
    x: 0.8, y: 1.5, w: 8, h: 0.45,
    fontSize: 14, fontFace: "Calibri",
    color: C.orange, bold: true, charSpacing: 4, margin: 0
  });
  s.addText(title, {
    x: 0.8, y: 2.1, w: 8, h: 1.2,
    fontSize: 36, fontFace: "Trebuchet MS",
    color: C.white, bold: true, margin: 0
  });
  if (subtitle) {
    s.addText(subtitle, {
      x: 0.8, y: 3.3, w: 8, h: 0.5,
      fontSize: 18, fontFace: "Calibri",
      color: C.lightLine, margin: 0
    });
  }
  return s;
}

/**
 * テーブルスライドを作成
 * @param {Object} slide - スライドオブジェクト
 * @param {string[]} headers - ヘッダー行
 * @param {string[][]} rows - データ行
 * @param {Object} opts - { x, y, w, colW }
 */
function addStyledTable(slide, headers, rows, opts = {}) {
  const x = opts.x || 0.6;
  const y = opts.y || 1.45;
  const w = opts.w || 8.8;
  const colW = opts.colW || undefined;

  const headerRow = headers.map(h => ({
    text: h,
    options: {
      bold: true, color: C.white,
      fill: { color: C.tableHead },
      fontSize: 12, fontFace: "Calibri",
      align: "center", valign: "middle"
    }
  }));

  const dataRows = rows.map((row, i) =>
    row.map((cell, j) => ({
      text: cell,
      options: {
        fontSize: 11, fontFace: "Calibri",
        color: j === 0 ? C.navy : C.bodyText,
        bold: j === 0,
        fill: { color: i % 2 === 0 ? C.tableAlt : C.white },
        align: j === 0 ? "left" : "center",
        valign: "middle"
      }
    }))
  );

  slide.addTable([headerRow, ...dataRows], {
    x, y, w, colW,
    rowH: 0.45,
    border: { pt: 0.5, color: C.lightLine }
  });
}

/**
 * アクセント付きカード（左にカラーバー）
 */
function addAccentCard(slide, x, y, w, h, accentColor, title, body) {
  slide.addShape("rect", {
    x, y, w, h,
    fill: { color: C.white }, shadow: makeCardShadow()
  });
  slide.addShape("rect", {
    x, y, w: 0.08, h,
    fill: { color: accentColor }
  });
  if (title) {
    slide.addText(title, {
      x: x + 0.25, y: y + 0.1, w: w - 0.45, h: 0.35,
      fontSize: 13, fontFace: "Trebuchet MS",
      color: C.navy, bold: true, margin: 0
    });
  }
  if (body) {
    slide.addText(body, {
      x: x + 0.25, y: y + (title ? 0.45 : 0.1),
      w: w - 0.45, h: h - (title ? 0.55 : 0.2),
      fontSize: 11, fontFace: "Calibri",
      color: C.bodyText, margin: 0
    });
  }
}

// ============================================================
// Exports
// ============================================================
module.exports = {
  C,
  makeShadow,
  makeCardShadow,
  iconToBase64Png,
  createPresentation,
  addContentSlide,
  addSectionTitle,
  addSubtitle,
  addFooter,
  addSectionDivider,
  addStyledTable,
  addAccentCard,
};
