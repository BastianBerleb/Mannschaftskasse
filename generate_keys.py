# generate_keys.py (Final - using the standard cryptography library)

import base64
from cryptography.hazmat.primitives.asymmetric import ec

# 1. Generate a private key using the P-256 curve (also known as SECP256R1)
private_key = ec.generate_private_key(ec.SECP256R1())

# 2. Derive the public key from the private key
public_key = private_key.public_key()

# 3. Get the raw private key value
private_key_bytes = private_key.private_numbers().private_value.to_bytes(32, byteorder='big')

# 4. Get the raw public key value in uncompressed format (x and y coordinates)
public_key_bytes = public_key.public_numbers().x.to_bytes(32, 'big') + \
                   public_key.public_numbers().y.to_bytes(32, 'big')

# Prepend the uncompressed point marker
public_key_bytes = b'\x04' + public_key_bytes

# 5. Encode both keys into URL-safe, unpadded base64 strings
private_key_str = base64.urlsafe_b64encode(private_key_bytes).rstrip(b'=').decode('utf-8')
public_key_str = base64.urlsafe_b64encode(public_key_bytes).rstrip(b'=').decode('utf-8')

print("VAPID Public Key:")
print(public_key_str)
print("\nVAPID Private Key:")
print(private_key_str)