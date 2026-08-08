#include <iostream>
#include <fstream>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <openssl/aes.h>
#include <openssl/err.h>

void handleErrors() {
    ERR_print_errors_fp(stderr);
    abort();
}

// Function to read the key from a file
bool readKeyFromFile(const std::string& keyFile, unsigned char* key, int& keyLen) {
    std::ifstream file(keyFile, std::ios::binary);
    if (!file.is_open()) {
        std::cerr << "Error opening key file: " << keyFile << std::endl;
        return false;
    }

    file.read(reinterpret_cast<char*>(key), AES_BLOCK_SIZE);
    keyLen = file.gcount();
    file.close();

    if (keyLen != AES_BLOCK_SIZE) {
        std::cerr << "Key size must be " << AES_BLOCK_SIZE << " bytes." << std::endl;
        return false;
    }

    return true;
}

// Function to encrypt the file
bool encryptFile(const std::string& inputFile, const std::string& outputFile, const unsigned char* key, int keyLen) {
    // Open input file
    std::ifstream inFile(inputFile, std::ios::binary);
    if (!inFile.is_open()) {
        std::cerr << "Error opening input file: " << inputFile << std::endl;
        return false;
    }

    // Open output file
    std::ofstream outFile(outputFile, std::ios::binary);
    if (!outFile.is_open()) {
        std::cerr << "Error opening output file: " << outputFile << std::endl;
        return false;
    }

    // Initialize OpenSSL EVP context for AES encryption
    EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
    if (!ctx) {
        handleErrors();
    }

    // Set up AES encryption context
    if (EVP_EncryptInit_ex(ctx, EVP_aes_256_cbc(), nullptr, key, nullptr) != 1) {
        handleErrors();
    }

    // Generate a random IV for encryption
    unsigned char iv[AES_BLOCK_SIZE];
    if (RAND_bytes(iv, AES_BLOCK_SIZE) != 1) {
        handleErrors();
    }

    // Write the IV at the beginning of the output file
    outFile.write(reinterpret_cast<char*>(iv), AES_BLOCK_SIZE);

    // Encrypt the file
    unsigned char inBuf[1024], outBuf[1024 + AES_BLOCK_SIZE];
    int inLen, outLen;

    while (inFile.read(reinterpret_cast<char*>(inBuf), sizeof(inBuf))) {
        inLen = inFile.gcount();
        if (EVP_EncryptUpdate(ctx, outBuf, &outLen, inBuf, inLen) != 1) {
            handleErrors();
        }
        outFile.write(reinterpret_cast<char*>(outBuf), outLen);
    }

    // Finalize the encryption
    if (EVP_EncryptFinal_ex(ctx, outBuf, &outLen) != 1) {
        handleErrors();
    }
    outFile.write(reinterpret_cast<char*>(outBuf), outLen);

    // Clean up
    EVP_CIPHER_CTX_free(ctx);
    inFile.close();
    outFile.close();

    return true;
}

int main(int argc, char* argv[]) {
    if (argc != 3) {
        std::cerr << "Usage: " << argv[0] << " <key_file> <file_to_encrypt>" << std::endl;
        return 1;
    }

    std::string keyFile = argv[1];
    std::string inputFile = argv[2];

    unsigned char key[AES_BLOCK_SIZE];
    int keyLen;

    // Read key from the key file
    if (!readKeyFromFile(keyFile, key, keyLen)) {
        return 1;
    }

    // Create output file name with .enc extension
    std::string outputFile = inputFile + ".enc";

    // Encrypt the file
    if (encryptFile(inputFile, outputFile, key, keyLen)) {
        std::cout << "File encrypted successfully: " << outputFile << std::endl;
    } else {
        std::cerr << "Encryption failed!" << std::endl;
        return 1;
    }

    return 0;
}
