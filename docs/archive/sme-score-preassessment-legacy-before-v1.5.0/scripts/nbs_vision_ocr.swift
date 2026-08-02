import AppKit
import Foundation
import Vision

guard CommandLine.arguments.count >= 2 else {
    FileHandle.standardError.write(Data("用法: nbs_vision_ocr.swift <image-path>\n".utf8))
    exit(2)
}

let imagePath = CommandLine.arguments[1]
guard
    let image = NSImage(contentsOfFile: imagePath),
    let tiff = image.tiffRepresentation,
    let bitmap = NSBitmapImageRep(data: tiff),
    let cgImage = bitmap.cgImage
else {
    FileHandle.standardError.write(Data("无法读取图片: \(imagePath)\n".utf8))
    exit(3)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.minimumTextHeight = 0.006

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    FileHandle.standardError.write(Data("OCR 失败: \(error)\n".utf8))
    exit(4)
}

let observations = (request.results ?? []).compactMap { observation -> (CGRect, Float, String)? in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    return (observation.boundingBox, candidate.confidence, candidate.string)
}.sorted {
    let rowDelta = abs($0.0.midY - $1.0.midY)
    if rowDelta > 0.004 { return $0.0.midY > $1.0.midY }
    return $0.0.minX < $1.0.minX
}

print("x\ty\tw\th\tconfidence\ttext")
for (box, confidence, rawText) in observations {
    let text = rawText
        .replacingOccurrences(of: "\t", with: " ")
        .replacingOccurrences(of: "\n", with: " ")
    print(String(format: "%.6f\t%.6f\t%.6f\t%.6f\t%.4f\t%@", box.minX, box.minY, box.width, box.height, confidence, text))
}
