import hashlib
import json
import struct
from pathlib import Path

import pytest

from anima_prompt_studio_v3.runtime.lora_library import LoraLibrary, validate_library_resources
from anima_prompt_studio_v3.core.lora_resolution import ResourceUnavailable


def tensor_file(path, value=b'1234'):
    header = json.dumps({'lora_unet_test.lora_down.weight': {'dtype': 'F32', 'shape': [1], 'data_offsets': [0, 4]}}).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack('<Q', len(header)) + header + value)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_scan_deduplicates_renames_and_preserves_classification(tmp_path):
    library = LoraLibrary(tmp_path / 'state.db', tmp_path / 'loras')
    digest = tensor_file(library.root / 'style.safetensors')
    tensor_file(library.root / 'nested' / 'same.safetensors')
    first = library.scan()
    assert len(first['items']) == 1
    library.update(digest, {'name': 'My style', 'family': 'anima', 'trigger_words': ['CF']})
    (library.root / 'style.safetensors').rename(library.root / 'renamed.safetensors')
    second = library.scan()['items'][0]
    assert second['id'] == digest and second['name'] == 'My style'
    assert second['trigger_words'] == ['CF']
    assert second['file_name'] == f'anima_library/{digest}.safetensors'
    assert second['present']


def test_changed_bytes_create_new_identity_and_missing_record_survives(tmp_path):
    library = LoraLibrary(tmp_path / 'state.db', tmp_path / 'loras')
    first = tensor_file(library.root / 'style.safetensors')
    library.scan()
    second = tensor_file(library.root / 'style.safetensors', b'abcd')
    items = {item['sha256']: item for item in library.scan()['items']}
    assert items[first]['present'] is False
    assert items[second]['present'] is True
    assert library.local_path(first) is None


def test_scan_rejects_incomplete_files_and_path_escape(tmp_path):
    library = LoraLibrary(tmp_path / 'state.db', tmp_path / 'loras')
    library.root.mkdir(parents=True)
    (library.root / 'partial.safetensors').write_bytes(struct.pack('<Q', 500) + b'{')
    result = library.scan()
    assert not result['items'] and result['errors']
    with pytest.raises(ValueError):
        library.get('../outside')


def test_library_selection_requires_confirmed_family_and_matching_bytes(tmp_path):
    db = tmp_path / 'state.db'
    library = LoraLibrary(db, tmp_path / 'loras')
    digest = tensor_file(library.root / 'style.safetensors')
    item = library.scan()['items'][0]
    resource = {'logical_id': 'library:' + digest, 'sha256': digest, 'file_name': item['file_name'], 'enabled': True}
    with pytest.raises(ResourceUnavailable):
        validate_library_resources(db, 'anima_turbo_v1_1', [resource])
    library.update(digest, {'family': 'anima'})
    validate_library_resources(db, 'anima_turbo_v1_1', [resource])
    with pytest.raises(ResourceUnavailable):
        validate_library_resources(db, 'moss_image_sft_int8', [resource])
    validate_library_resources(db, 'moss_image_sft_int8', [{**resource, 'enabled': False}])
    with pytest.raises(ResourceUnavailable):
        validate_library_resources(db, 'anima_turbo_v1_1', [{**resource, 'file_name': 'wrong.safetensors'}])


def test_local_path_rechecks_file_identity_after_scan(tmp_path):
    library = LoraLibrary(tmp_path / 'state.db', tmp_path / 'loras')
    digest = tensor_file(library.root / 'style.safetensors')
    library.scan()
    tensor_file(library.root / 'style.safetensors', b'abcd')
    with pytest.raises(ValueError):
        library.local_path(digest)


@pytest.mark.parametrize('dtype,shape', [('NONSENSE', [1]), ('F32', [1000])])
def test_scan_rejects_invalid_dtype_or_tensor_size(tmp_path, dtype, shape):
    library = LoraLibrary(tmp_path / 'state.db', tmp_path / 'loras')
    path = library.root / 'wrong.safetensors'
    path.parent.mkdir()
    header = json.dumps({'lora_unet_test.weight': {'dtype': dtype, 'shape': shape, 'data_offsets': [0, 4]}}).encode()
    path.write_bytes(struct.pack('<Q', len(header)) + header + b'1234')
    result = library.scan()
    assert not result['items'] and result['errors']


def test_metadata_normalizes_empty_and_duplicate_trigger_words(tmp_path):
    library = LoraLibrary(tmp_path / 'state.db', tmp_path / 'loras')
    sha = tensor_file(library.root / 'style.safetensors')
    library.scan()
    item = library.update(sha, {'trigger_words': [' CF ', '', 'CF'], 'model_profiles': [' ', 'anima_turbo_v1_1']})
    assert item['trigger_words'] == ['CF']
    assert item['model_profiles'] == ['anima_turbo_v1_1']
