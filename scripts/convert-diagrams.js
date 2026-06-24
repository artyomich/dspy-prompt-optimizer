const fs = require('fs');
const path = require('path');

// Load js-plantuml
const plantumlCode = fs.readFileSync('/tmp/plantuml.js', 'utf8');
eval(plantumlCode);

// Load main.js for rendering
const mainCode = fs.readFileSync('/tmp/main.js', 'utf8');
eval(mainCode);

const docsDir = path.join(__dirname, '..', 'docs');
const pumlFiles = ['C1_context', 'C2_container', 'C3_component', 'C4_code'];

async function convertPumlToJpg(pumlContent, outputFormat) {
  return new Promise((resolve, reject) => {
    try {
      const encoder = new netty.java.util.zip.GZIPOutputStream(
        new java.io.ByteArrayOutputStream()
      );
      const writer = new java.io.OutputStreamWriter(encoder, 'UTF-8');
      writer.write(pumlContent);
      writer.flush();
      writer.close();
      encoder.finish();
      const compressed = encoder.cOy().cg();

      const decoder = new netty.java.util.zip.GZIPInputStream(
        new java.io.ByteArrayInputStream(compressed)
      );
      const reader = new java.io.InputStreamReader(decoder);
      const chars = new Array(100000);
      let totalLen = 0;
      let read;
      while ((read = reader.read(chars, 0, chars.length)) > 0) {
        totalLen += read;
      }
      reader.close();
      const decoded = new String(chars.slice(0, totalLen));

      const imgEncoder = new com.plantuml.img.ImgEncoder();
      const imgData = imgEncoder.encode(decoded);
      const jpgBuffer = imgData.toJpg();

      resolve(jpgBuffer);
    } catch (e) {
      reject(e);
    }
  });
}

// Simpler approach: use plantuml.js directly
async function convertWithPlantUml(pumlContent) {
  return new Promise((resolve, reject) => {
    try {
      const encoder = new netty.java.util.zip.GZIPOutputStream(
        new java.io.ByteArrayOutputStream()
      );
      const writer = new java.io.OutputStreamWriter(encoder, 'UTF-8');
      writer.write(pumlContent);
      writer.close();
      encoder.finish();
      const compressed = encoder.cOy().cg();

      const decoder = new netty.java.util.zip.GZIPInputStream(
        new java.io.ByteArrayInputStream(compressed)
      );
      const reader = new java.io.InputStreamReader(decoder);
      const chars = new Array(100000);
      let totalLen = 0;
      let read;
      while ((read = reader.read(chars, 0, chars.length)) > 0) {
        totalLen += read;
      }
      reader.close();
      const decoded = new String(chars.slice(0, totalLen));

      const imgEncoder = new com.plantuml.img.ImgEncoder();
      const imgData = imgEncoder.encode(decoded);
      const jpgBuffer = imgData.toJpg();

      resolve(jpgBuffer);
    } catch (e) {
      reject(e);
    }
  });
}

async function main() {
  for (const name of pumlFiles) {
    const pumlPath = path.join(docsDir, name + '.puml');
    const jpgPath = path.join(docsDir, name + '.jpg');
    
    if (!fs.existsSync(pumlPath)) {
      console.log(`Skipping ${name}: puml file not found`);
      continue;
    }

    const pumlContent = fs.readFileSync(pumlPath, 'utf8');
    
    try {
      const jpgBuffer = await convertWithPlantUml(pumlContent);
      fs.writeFileSync(jpgPath, Buffer.from(jpgBuffer));
      console.log(`Converted: ${name}.puml -> ${name}.jpg (${jpgBuffer.length} bytes)`);
    } catch (e) {
      console.error(`Error converting ${name}:`, e.message);
    }
  }
}

main().catch(console.error);