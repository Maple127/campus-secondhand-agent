package campus.secondhand.service;

import campus.secondhand.common.BusinessException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

/**
 * 本地图片存储。
 *
 * 从 ProductController 中抽出：原实现把文件落盘逻辑写在 Controller 里，
 * Agent 代发布时无法复用，只能复制粘贴。
 */
@Slf4j
@Service
public class FileStorageService {

    /** 允许的图片扩展名，避免上传可执行文件 */
    private static final List<String> ALLOWED_EXT = List.of(".jpg", ".jpeg", ".png", ".webp", ".gif");

    private final Path uploadDir;

    public FileStorageService(@Value("${app.upload-dir:uploads}") String uploadDir) {
        this.uploadDir = Paths.get(uploadDir).toAbsolutePath();
    }

    /** 保存上传图片，返回可访问路径（形如 /uploads/xxx.png） */
    public String store(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            return null;
        }
        String ext = extensionOf(file.getOriginalFilename());
        if (!ALLOWED_EXT.contains(ext)) {
            throw BusinessException.badRequest("不支持的图片格式：" + (ext.isEmpty() ? "未知" : ext));
        }
        try {
            Files.createDirectories(uploadDir);
            String filename = UUID.randomUUID().toString().replace("-", "") + ext;
            Path target = uploadDir.resolve(filename);
            Files.copy(file.getInputStream(), target, StandardCopyOption.REPLACE_EXISTING);
            return "/uploads/" + filename;
        } catch (IOException e) {
            log.error("保存图片失败", e);
            throw new BusinessException(500, "STORAGE_ERROR", "图片上传失败，请重试");
        }
    }

    public Path getUploadDir() {
        return uploadDir;
    }

    private static String extensionOf(String original) {
        if (original == null || !original.contains(".")) {
            return "";
        }
        return original.substring(original.lastIndexOf('.')).toLowerCase(Locale.ROOT);
    }
}
