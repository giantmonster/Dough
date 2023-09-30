
import os
import tempfile
import streamlit as st
import replicate
from typing import List
from PIL import Image
import uuid
import urllib
from backend.models import InternalFileObject
from shared.constants import REPLICATE_USER, SERVER, InternalFileTag, InternalFileType, ServerType
from ui_components.constants import MASK_IMG_LOCAL_PATH, TEMP_MASK_FILE
from ui_components.models import InternalAIModelObject, InternalFrameTimingObject, InternalSettingObject
from utils.constants import ImageStage, MLQueryObject
from utils.data_repo.data_repo import DataRepo
from utils.ml_processor.ml_interface import get_ml_client
from utils.ml_processor.replicate.constants import REPLICATE_MODEL


def trigger_restyling_process(timing_uuid, update_inference_settings, \
                              transformation_stage, promote_new_generation, **kwargs):
    from ui_components.methods.common_methods import add_image_variant, promote_image_variant

    data_repo = DataRepo()
    
    timing: InternalFrameTimingObject = data_repo.get_timing_from_uuid(timing_uuid)
    project_settings: InternalSettingObject = data_repo.get_project_setting(timing.project.uuid)
    
    if transformation_stage == ImageStage.SOURCE_IMAGE.value:
        source_image = timing.source_image
    else:
        variants: List[InternalFileObject] = timing.alternative_images_list
        number_of_variants = len(variants)
        source_image = timing.primary_image

    query_obj = MLQueryObject(
        timing_uuid, 
        image_uuid=source_image.uuid, 
        width=project_settings.width, 
        height=project_settings.height, 
        **kwargs
    )

    if update_inference_settings is True:
        prompt = prompt.replace(",", ".")
        prompt = prompt.replace("\n", "")
        data_repo.update_project_setting(
            timing.project.uuid,
            default_prompt=prompt,
            default_strength=query_obj.strength,
            default_model_id=query_obj.model_uuid,
            default_negative_prompt=query_obj.negative_prompt,
            default_guidance_scale=query_obj.guidance_scale,
            default_seed=query_obj.seed,
            default_num_inference_steps=query_obj.num_inference_steps,
            default_which_stage_to_run_on=query_obj.transformation_stage,
            default_custom_models=query_obj.custom_models,
            default_adapter_type=query_obj.adapter_type,
            default_low_threshold=query_obj.low_threshold,
            default_high_threshold=query_obj.high_threshold
        )

    dynamic_prompting(prompt, source_image, timing_uuid)

    # TODO: reverse the log creation flow (create log first and then pass the uuid)
    output_file = restyle_images(query_obj)

    if output_file != None:
        add_image_variant(output_file.uuid, timing_uuid)

        if promote_new_generation == True:
            timing = data_repo.get_timing_from_uuid(timing_uuid)
            variants = timing.alternative_images_list
            number_of_variants = len(variants)
            if number_of_variants == 1:
                print("No new generation to promote")
            else:
                promote_image_variant(timing_uuid, number_of_variants - 1)
    else:
        print("No new generation to promote")

def restyle_images(query_obj: MLQueryObject) -> InternalFileObject:
    model_name = query_obj.model_name
    if model_name == "LoRA":
        output_file = prompt_model_lora(query_obj)
    elif model_name == "controlnet":
        output_file = prompt_model_controlnet(query_obj)
    elif model_name == "Dreambooth":
        output_file = prompt_model_dreambooth(query_obj)
    else:
        model = REPLICATE_MODEL.get_model_by_name(model_name)   # TODO: remove this dependency
        output_file = prompt_model(model, query_obj)

    return output_file

def prompt_model(model, query_obj: MLQueryObject) -> InternalFileObject:
    ml_client = get_ml_client()
    data_repo = DataRepo()

    output, log = ml_client.predict_model_output_standardized(model, query_obj)
    
    filename = str(uuid.uuid4()) + ".png"
    output_file = data_repo.create_file(
        name=filename, 
        type=InternalFileType.IMAGE.value,
        hosted_url=output[0], 
        inference_log_id=log.uuid
    )

    return output_file

def prompt_model_lora(query_obj: MLQueryObject) -> InternalFileObject:
    data_repo = DataRepo()

    timing_uuid = query_obj.timing_uuid
    source_image_file: InternalFileObject = data_repo.get_file_from_uuid(query_obj.image_uuid)

    timing: InternalFrameTimingObject = data_repo.get_timing_from_uuid(
        timing_uuid)
    project_settings: InternalSettingObject = data_repo.get_project_setting(
        timing.project.uuid)

    lora_urls = ""
    lora_scales = ""
    if "lora_model_1_url" in st.session_state and st.session_state["lora_model_1_url"]:
        lora_urls += st.session_state["lora_model_1_url"]
        lora_scales += "0.5"
    if "lora_model_2_url" in st.session_state and st.session_state["lora_model_2_url"]:
        ctn = "" if not len(lora_urls) else " | "
        lora_urls += ctn + st.session_state["lora_model_2_url"]
        lora_scales += ctn + "0.5"
    if st.session_state["lora_model_3_url"]:
        ctn = "" if not len(lora_urls) else " | "
        lora_urls += ctn + st.session_state["lora_model_3_url"]
        lora_scales += ctn + "0.5"

    source_image = source_image_file.location
    if source_image[:4] == "http":
        input_image = source_image
    else:
        input_image = open(source_image, "rb")

    if timing.adapter_type != "None":
        if source_image[:4] == "http":
            adapter_condition_image = source_image
        else:
            adapter_condition_image = open(source_image, "rb")
    else:
        adapter_condition_image = ""

    inputs = {
        'prompt': timing.prompt,
        'negative_prompt': timing.negative_prompt,
        'width': project_settings.width,
        'height': project_settings.height,
        'num_outputs': 1,
        'image': input_image,
        'num_inference_steps': timing.num_inteference_steps,
        'guidance_scale': timing.guidance_scale,
        'prompt_strength': timing.strength,
        'scheduler': "DPMSolverMultistep",
        'lora_urls': lora_urls,
        'lora_scales': lora_scales,
        'adapter_type': timing.adapter_type,
        'adapter_condition_image': adapter_condition_image,
    }

    ml_client = get_ml_client()
    max_attempts = 3
    attempts = 0
    while attempts < max_attempts:
        try:
            output, log = ml_client.predict_model_output(
                REPLICATE_MODEL.clones_lora_training_2, **inputs)
            print(output)
            filename = str(uuid.uuid4()) + ".png"
            file: InternalFileObject = data_repo.create_file(name=filename, type=InternalFileType.IMAGE.value,
                                                             hosted_url=output[0], inference_log_id=log.uuid)
            return file
        except replicate.exceptions.ModelError as e:
            if "NSFW content detected" in str(e):
                print("NSFW content detected. Attempting to rerun code...")
                attempts += 1
                continue
            else:
                raise e
        except Exception as e:
            raise e

def prompt_model_dreambooth(query_obj: MLQueryObject):
    data_repo = DataRepo()

    if not ('dreambooth_model_uuid' in st.session_state and st.session_state['dreambooth_model_uuid']):
        st.error('No dreambooth model selected')
        return
    
    timing_uuid = query_obj.timing_uuid
    source_image_file: InternalFileObject = data_repo.get_file_from_uuid(query_obj.image_uuid)
    timing: InternalFrameTimingObject = data_repo.get_timing_from_uuid(
        timing_uuid)
    timing_details: List[InternalFrameTimingObject] = data_repo.get_timing_list_from_project(
        timing.project.uuid)

    project_settings: InternalSettingObject = data_repo.get_project_setting(
        timing.project.uuid)
    
    dreambooth_model: InternalAIModelObject = data_repo.get_ai_model_from_uuid(st.session_state['dreambooth_model_uuid'])
    
    model_name = dreambooth_model.name
    image_number = timing.aux_frame_index
    prompt = timing.prompt
    strength = timing.strength
    negative_prompt = timing.negative_prompt
    guidance_scale = timing.guidance_scale
    seed = timing.seed
    num_inference_steps = timing.num_inteference_steps

    model_id = dreambooth_model.replicate_url

    ml_client = get_ml_client()

    source_image = source_image_file.location
    if timing_details[image_number].adapter_type == "Yes":
        if source_image.startswith("http"):
            control_image = source_image
        else:
            control_image = open(source_image, "rb")
    else:
        control_image = None

    # version of models that were custom created has to be fetched
    if not dreambooth_model.version:
        version = ml_client.get_model_version_from_id(model_id)
        data_repo.update_ai_model(uuid=dreambooth_model.uuid, version=version)
    else:
        version = dreambooth_model.version

    model_version = ml_client.get_model_by_name(
        f"{REPLICATE_USER}/{model_name}", version)

    if source_image.startswith("http"):
        input_image = source_image
    else:
        input_image = open(source_image, "rb")

    input_data = {
        "image": input_image,
        "prompt": prompt,
        "prompt_strength": float(strength),
        "height": int(project_settings.height),
        "width": int(project_settings.width),
        "disable_safety_check": True,
        "negative_prompt": negative_prompt,
        "guidance_scale": float(guidance_scale),
        "seed": int(seed),
        "num_inference_steps": int(num_inference_steps)
    }

    if control_image != None:
        input_data['control_image'] = control_image

    output = model_version.predict(**input_data)

    for i in output:
        filename = str(uuid.uuid4()) + ".png"
        image_file = data_repo.create_file(
            name=filename, type=InternalFileType.IMAGE.value, hosted_url=i, tag=InternalFileTag.GENERATED_VIDEO.value)
        return image_file

    return None

def prompt_model_controlnet(query_obj: MLQueryObject):
    data_repo = DataRepo()
    timing: InternalFrameTimingObject = data_repo.get_timing_from_uuid(
        timing_uuid)

    timing_uuid = query_obj.timing_uuid
    intput_image_file: InternalFileObject = data_repo.get_file_from_uuid(query_obj.image_uuid)
    input_image = intput_image_file.location
    
    if timing.adapter_type == "normal":
        model = REPLICATE_MODEL.jagilley_controlnet_normal
    elif timing.adapter_type == "canny":
        model = REPLICATE_MODEL.jagilley_controlnet_canny
    elif timing.adapter_type == "hed":
        model = REPLICATE_MODEL.jagilley_controlnet_hed
    elif timing.adapter_type == "scribble":
        model = REPLICATE_MODEL.jagilley_controlnet_scribble
        if timing.canny_image != "":
            input_image = timing.canny_image
    elif timing.adapter_type == "seg":
        model = REPLICATE_MODEL.jagilley_controlnet_seg
    elif timing.adapter_type == "hough":
        model = REPLICATE_MODEL.jagilley_controlnet_hough
    elif timing.adapter_type == "depth2img":
        model = REPLICATE_MODEL.jagilley_controlnet_depth2img
    elif timing.adapter_type == "pose":
        model = REPLICATE_MODEL.jagilley_controlnet_pose

    if not input_image.startswith("http"):
        input_image = open(input_image, "rb")

    inputs = {
        'image': input_image,
        'prompt': timing.prompt,
        'num_samples': "1",
        'image_resolution': "512",
        'ddim_steps': timing.num_inteference_steps,
        'scale': timing.guidance_scale,
        'eta': 0,
        'seed': timing.seed,
        'a_prompt': "best quality, extremely detailed",
        'n_prompt': timing.negative_prompt + ", longbody, lowres, bad anatomy, bad hands, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality",
        'detect_resolution': 512,
        'bg_threshold': 0,
        'low_threshold': timing.low_threshold,
        'high_threshold': timing.high_threshold,
    }

    ml_client = get_ml_client()
    output, log = ml_client.predict_model_output(model, **inputs)

    filename = str(uuid.uuid4()) + ".png"
    output_file: InternalFileObject = data_repo.create_file(name=filename, type=InternalFileType.IMAGE.value,
                                                           hosted_url=output[0], inference_log_id=log.uuid)
    return output_file

def prompt_clip_interrogator(input_image, which_model, best_or_fast):
    if which_model == "Stable Diffusion 1.5":
        which_model = "ViT-L-14/openai"
    elif which_model == "Stable Diffusion 2":
        which_model = "ViT-H-14/laion2b_s32b_b79k"

    if not input_image.startswith("http"):
        input_image = open(input_image, "rb")

    ml_client = get_ml_client()
    output, _ = ml_client.predict_model_output(
        REPLICATE_MODEL.clip_interrogator, image=input_image, clip_model_name=which_model, mode=best_or_fast)

    return output

def prompt_model_blip2(input_image, query):
    if not input_image.startswith("http"):
        input_image = open(input_image, "rb")

    ml_client = get_ml_client()
    output, _ = ml_client.predict_model_output(
        REPLICATE_MODEL.salesforce_blip_2, image=input_image, question=query)

    return output

def facial_expression_recognition(input_image):
    if not input_image.startswith("http"):
        input_image = open(input_image, "rb")

    ml_client = get_ml_client()
    output, _ = ml_client.predict_model_output(
        REPLICATE_MODEL.phamquiluan_face_recognition, input_path=input_image)

    emo_label = output[0]["emo_label"]
    if emo_label == "disgust":
        emo_label = "disgusted"
    elif emo_label == "fear":
        emo_label = "fearful"
    elif emo_label == "surprised":
        emo_label = "surprised"
    emo_proba = output[0]["emo_proba"]
    if emo_proba > 0.95:
        emotion = (f"very {emo_label} expression")
    elif emo_proba > 0.85:
        emotion = (f"{emo_label} expression")
    elif emo_proba > 0.75:
        emotion = (f"somewhat {emo_label} expression")
    elif emo_proba > 0.65:
        emotion = (f"slightly {emo_label} expression")
    elif emo_proba > 0.55:
        emotion = (f"{emo_label} expression")
    else:
        emotion = (f"neutral expression")
    return emotion

def inpainting(input_image: str, prompt, negative_prompt, timing_uuid, invert_mask, pass_mask=False) -> InternalFileObject:
    data_repo = DataRepo()
    timing: InternalFrameTimingObject = data_repo.get_timing_from_uuid(
        timing_uuid)

    if pass_mask == False:
        mask = timing.mask.location
    else:
        # TODO: store the local temp files in the db too
        if SERVER != ServerType.DEVELOPMENT.value:
            mask = timing.project.get_temp_mask_file(TEMP_MASK_FILE).location
        else:
            mask = MASK_IMG_LOCAL_PATH

    if not mask.startswith("http"):
        mask = open(mask, "rb")

    if not input_image.startswith("http"):
        input_image = open(input_image, "rb")

    ml_client = get_ml_client()
    output, log = ml_client.predict_model_output(REPLICATE_MODEL.andreas_sd_inpainting, mask=mask, image=input_image, prompt=prompt,
                                            invert_mask=invert_mask, negative_prompt=negative_prompt, num_inference_steps=25)

    file_name = str(uuid.uuid4()) + ".png"
    image_file = data_repo.create_file(
        name=file_name, type=InternalFileType.IMAGE.value, hosted_url=output[0], inference_log_id=log.uuid)

    return image_file

def remove_background(input_image):
    if not input_image.startswith("http"):
        input_image = open(input_image, "rb")

    ml_client = get_ml_client()
    output, _ = ml_client.predict_model_output(
        REPLICATE_MODEL.pollination_modnet, image=input_image)
    return output

def create_depth_mask_image(input_image, layer, timing_uuid):
    from ui_components.methods.common_methods import create_or_update_mask
    
    if not input_image.startswith("http"):
        input_image = open(input_image, "rb")

    ml_client = get_ml_client()
    output, log = ml_client.predict_model_output(
        REPLICATE_MODEL.cjwbw_midas, image=input_image, model_type="dpt_beit_large_512")
    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png", mode='wb')
        # urllib.request.urlretrieve(output, "videos/temp/depth.png")
        with urllib.request.urlopen(output) as response, open(temp_file.name, 'wb') as out_file:
            out_file.write(response.read())
    except Exception as e:
        print(e)

    depth_map = Image.open(temp_file.name)
    os.remove(temp_file.name)
    depth_map = depth_map.convert("L")  # Convert to grayscale image
    pixels = depth_map.load()
    mask = Image.new("L", depth_map.size)
    mask_pixels = mask.load()

    fg_mask = Image.new("L", depth_map.size) if "Foreground" in layer else None
    mg_mask = Image.new(
        "L", depth_map.size) if "Middleground" in layer else None
    bg_mask = Image.new("L", depth_map.size) if "Background" in layer else None

    fg_pixels = fg_mask.load() if fg_mask else None
    mg_pixels = mg_mask.load() if mg_mask else None
    bg_pixels = bg_mask.load() if bg_mask else None

    for i in range(depth_map.size[0]):
        for j in range(depth_map.size[1]):
            depth_value = pixels[i, j]

            if fg_pixels:
                fg_pixels[i, j] = 0 if depth_value > 200 else 255
            if mg_pixels:
                mg_pixels[i, j] = 0 if depth_value <= 200 and depth_value > 50 else 255
            if bg_pixels:
                bg_pixels[i, j] = 0 if depth_value <= 50 else 255

            mask_pixels[i, j] = 255
            if fg_pixels:
                mask_pixels[i, j] &= fg_pixels[i, j]
            if mg_pixels:
                mask_pixels[i, j] &= mg_pixels[i, j]
            if bg_pixels:
                mask_pixels[i, j] &= bg_pixels[i, j]

    return create_or_update_mask(timing_uuid, mask)

def dynamic_prompting(prompt, source_image, timing_uuid):
    data_repo = DataRepo()
    timing: InternalFrameTimingObject = data_repo.get_timing_from_uuid(
        timing_uuid)

    if "[expression]" in prompt:
        prompt_expression = facial_expression_recognition(source_image)
        prompt = prompt.replace("[expression]", prompt_expression)

    if "[location]" in prompt:
        prompt_location = prompt_model_blip2(
            source_image, "What's surrounding the character?")
        prompt = prompt.replace("[location]", prompt_location)

    if "[mouth]" in prompt:
        prompt_mouth = prompt_model_blip2(
            source_image, "is their mouth open or closed?")
        prompt = prompt.replace("[mouth]", "mouth is " + str(prompt_mouth))

    if "[looking]" in prompt:
        prompt_looking = prompt_model_blip2(
            source_image, "the person is looking")
        prompt = prompt.replace("[looking]", "looking " + str(prompt_looking))

    data_repo.update_specific_timing(timing_uuid, prompt=prompt)